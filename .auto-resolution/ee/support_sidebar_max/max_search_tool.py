import logging

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SITEMAP_URL = "https://posthog.com/sitemap/sitemap-0.xml"

STATUS_PAGE_URL = "https://status.posthog.com"

HOGQL_PRIORITY_URLS = [
    "https://posthog.com/docs/hogql",
    "https://posthog.com/docs/hogql/aggregations",
    "https://posthog.com/docs/hogql/clickhouse-functions",
    "https://posthog.com/docs/hogql/expressions",
    "https://posthog.com/docs/product-analytics/sql",
]


def is_hogql_query(query):
    hogql_keywords = ["hogql", "sql", "query", "aggregate", "function", "expression"]
    return any(keyword in query.lower() for keyword in hogql_keywords)


def is_status_query(query):
    status_keywords = ["status", "incident", "outage", "downtime", "ingestion", "slow", "lag", "delays"]
    return any(keyword in query.lower() for keyword in status_keywords)


def get_relevant_urls(query):
    urls = []

    try:
        response = requests.get(SITEMAP_URL)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "xml")
        for url in soup.find_all("loc"):
            loc = url.text
            if "/questions/" not in loc:
                urls.append(loc)
        if is_hogql_query(query):
            urls.extend(HOGQL_PRIORITY_URLS)
        urls.append(STATUS_PAGE_URL)
        return urls
    except requests.RequestException as e:
        logger.error(f"Error fetching sitemap: {str(e)}")  # noqa: TRY400
        return urls


def prioritize_urls(urls, query):
    priority_dirs = {
        "docs": ["docs", "tutorials"],
        "how": ["docs", "tutorials"],
        "pricing": ["pricing"],
        "jobs": ["careers"],
        "history": ["about", "handbook", "blog"],
        "teams": ["teams"],
    }

    query_type = "docs"  # default
    for key in priority_dirs:
        if key in query.lower():
            query_type = key
            break

    def calculate_relevance(url):
        query_words = query.lower().split()
        url_lower = url.lower()
        word_match_score = sum(3 if word in url_lower else 1 for word in query_words if word in url_lower)
        url_depth = len(url.strip("/").split("/"))
        depth_score = min(url_depth, 5)
        priority_score = 5 if any(dir in url for dir in priority_dirs[query_type]) else 0

        if is_hogql_query(query) and url in HOGQL_PRIORITY_URLS:
            priority_score += 10

        if is_status_query(query) and url == STATUS_PAGE_URL:
            priority_score += 15

        return (word_match_score * 2) + (depth_score * 1.5) + priority_score

    return sorted(urls, key=calculate_relevance, reverse=True)


def max_search_tool(query):
    relevant_urls = get_relevant_urls(query)
    prioritized_urls = prioritize_urls(relevant_urls, query)
    results = []
    errors = []

    max_urls_to_process = 30
    max_chars = 10000
    relevance_threshold = 0.6
    min_results = 5

    def has_highly_relevant_results(results, threshold=2):
        return len(results) >= threshold and all(
            len(result["relevant_passages"]) >= 2 for result in results[:threshold]
        )

    for url in prioritized_urls[:max_urls_to_process]:
        try:
            logger.info(f"Searching {url}")
            response = requests.get(url, allow_redirects=True, timeout=180)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, "html.parser")

            for script in soup(["script", "style"]):
                script.decompose()
            text = soup.get_text()
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            text = "\n".join(chunk for chunk in chunks if chunk)

            paragraphs = text.split("\n\n")
            relevant_passages = []
            for i, paragraph in enumerate(paragraphs):
                relevance_score = sum(word.lower() in paragraph.lower() for word in query.split())
                if relevance_score > 0:
                    relevant_text = paragraph
                    char_count = len(relevant_text)

                    for j in range(i + 1, min(i + 5, len(paragraphs))):
                        if char_count + len(paragraphs[j]) <= max_chars:
                            relevant_text += "\n\n" + paragraphs[j]
                            char_count += len(paragraphs[j])
                        else:
                            break

                    heading = "Unknown Section"
                    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
                        if tag.string and tag.string in paragraph:
                            heading = tag.string
                            break

                    relevant_passages.append(
                        {
                            "text": relevant_text[:10000],
                            "url": url,
                            "heading": heading,
                            "relevance_score": relevance_score,
                        }
                    )

            if relevant_passages:
                relevant_passages.sort(key=lambda x: x["relevance_score"], reverse=True)
                result = {
                    "page_title": soup.title.string if soup.title else "Untitled",
                    "url": url,
                    "relevant_passages": relevant_passages[:4],
                }
                results.append(result)

                if len(results) >= min_results and relevant_passages[0]["relevance_score"] > relevance_threshold:
                    logger.info(f"Found sufficient relevant results so stopping search.")
                    break

                if has_highly_relevant_results(results):
                    logger.info("Found highly relevant results so stopping search.")
                    break

        except requests.RequestException as e:
            error_message = f"Error fetching {url}: {str(e)}"
            logger.error(error_message)  # noqa: TRY400
            errors.append(error_message)

    if not results and not errors:
        return (
            "Well this is odd. My searches aren't finding anything for that. Could you try asking with different words?"
        )
    elif errors and not results:
        return f"Oof. Sorry about this. I ran into errors when trying to search: {'; '.join(errors)}"
    else:
        return results[:5]
