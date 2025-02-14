import os
import time
import requests
import argparse
import json
from colorama import Fore, Style, init
from dotenv import load_dotenv
import logging
from bs4 import BeautifulSoup
from rich.console import Console
from rich.progress import Progress, SpinnerColumn
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# Initialize colorama
init(autoreset=True)

# Initialize logging
logging.basicConfig(level=logging.INFO)

# Load environment variables from .env file
load_dotenv()

BASE_URL = "https://gist.github.com"

def handle_response(response: requests.Response, authenticated: bool = True) -> bool:
    """Handle the response from an API request."""
    if response.status_code == 403:
        print(f"{Fore.RED}[-] Forbidden: Check your token and permissions.{Style.RESET_ALL}")
        return False
    elif response.status_code == 429:
        print(f"{Fore.YELLOW}[!] Rate limit exceeded. Waiting for retry...{Style.RESET_ALL}")
        retry_after = int(response.headers.get('Retry-After', 1))
        time.sleep(retry_after)
        return True
    elif response.status_code != 200:
        print(f"{Fore.RED}[-] Error with status code: {Fore.RED}{response.status_code}{Style.RESET_ALL}")
        return False

    rate_limit_remaining = int(response.headers.get('X-RateLimit-Remaining', 0))
    rate_limit_reset = int(response.headers.get('X-RateLimit-Reset', 0))

    threshold = 5 if authenticated else 1

    if rate_limit_remaining < threshold:
        reset_time = max(rate_limit_reset - time.time(), 0)
        if reset_time > 180:  # 180 seconds = 3 minutes
            print(f"{Fore.RED}[-] Rate limit reset time exceeds 3 minutes. Stopping further processing.{Style.RESET_ALL}")
            return True
        else:
            print(f"{Fore.YELLOW}[!] Rate limit reset time is less than 3 minutes. Waiting for {reset_time:.2f} seconds until reset.{Style.RESET_ALL}")
            time.sleep(reset_time)

    return True

class Item:
    def __init__(self, creator, title, link, guid, pub_date, content):
        self.creator = creator
        self.title = title
        self.link = link
        self.guid = guid
        self.pub_date = pub_date
        self.content = content

def fetch_html(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.text
    except requests.RequestException as e:
        print(f"An error occurred while fetching HTML: {e}")
        return None

def search_github_gists(query, page_limit=10, rate_limit=None, verbose=False):
    next_path = f"/search?q={query}"

    session = requests.Session()
    retry_strategy = Retry(total=5, backoff_factor=2, status_forcelist=[429])
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount('https://', adapter)

    keyword_result = {"keyword": query, "gist_urls": []}

    if verbose:
        print(f"Processing keyword: {query}")

    with Progress(SpinnerColumn(spinner_name="point")) as progress:
        task = progress.add_task(f"Searching for '{query}'...", total=page_limit)
        for _ in range(page_limit):
            url = f"{BASE_URL}{next_path}"
            html = fetch_html(url)

            if html:
                soup = BeautifulSoup(html, 'html.parser')
                gist_snippets = soup.select(".gist-snippet")
                for gist_snippet in gist_snippets:
                    # Extract gist URL
                    gist_url = "https://gist.github.com" + gist_snippet.find("a", href=True)['href']
                    keyword_result["gist_urls"].append(gist_url)
                
                next_link = soup.find("a", rel="next")
                if next_link:
                    next_path = next_link['href']
                else:
                    break

                progress.update(task, advance=1)
            
            if rate_limit:
                time.sleep(1 / rate_limit)

        if verbose:
            print(f"Finished processing keyword: {query}. Found {len(keyword_result['gist_urls'])} URLs.")
    return keyword_result

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Search GitHub Gists for specific keywords.")
    parser.add_argument("-k", "--keyword", help="Single keyword to search")
    parser.add_argument("-kf", "--keyword-file", help="File containing keywords to search")
    parser.add_argument("-o", "--output", help="Output file to save results")
    parser.add_argument("-r", "--rate-limit", type=float, help="Number of requests per second to limit")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose mode")
    args = parser.parse_args()

    if not (args.keyword or args.keyword_file):
        parser.error("Please provide either a single keyword or a keyword file.")

    if args.keyword and args.keyword_file:
        parser.error("Please provide either a single keyword or a keyword file, not both.")

    if args.keyword:
        keywords = [args.keyword]
    else:
        with open(args.keyword_file, 'r') as file:
            keywords = [line.strip() for line in file.readlines()]

    processed_keywords = set()

    for keyword in keywords:
        if keyword not in processed_keywords:
            result = search_github_gists(query=keyword, rate_limit=args.rate_limit, verbose=args.verbose)
            processed_keywords.add(keyword)
            if args.output:
                with open(args.output, 'a') as output_file:
                    json.dump(result, output_file, indent=4)
                    output_file.write('\n')
            else:
                print(json.dumps(result, indent=4))
