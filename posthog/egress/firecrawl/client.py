"""Typed client for the Firecrawl endpoints PostHog calls: a single-page scrape and a web search.

Firecrawl fetches and renders a page server-side and returns the extracted formats plus page
metadata for ``POST /v2/scrape``, and ranked web results for ``POST /v2/search``. Crawl and map are
separate products with their own credit cost and are not exposed until something needs them.
"""

from collections.abc import Mapping, Sequence
from typing import Literal, cast

from django.conf import settings

from posthog.dataclasses import frozen
from posthog.egress.firecrawl.transport import firecrawl_request
from posthog.egress.limiter.policies import Priority

FIRECRAWL_API_BASE = "https://api.firecrawl.dev"
SCRAPE_ENDPOINT = "/v2/scrape"

# The formats we have a use for. Firecrawl offers more (branding, screenshots, JSON extraction,
# change tracking); add them here when a caller needs one, so the request body stays a checked shape.
#
# Formats are not equal in cost. Firecrawl runs an LLM pass for some of them, and the credit price
# hides it: one scrape of the same page measured 1.1s for markdown alone, 3.7s adding summary, and
# 15.6s adding branding, all billed as a single credit. Weigh a new format against the caller's
# latency budget rather than its price.
ScrapeFormat = Literal["markdown", "summary"]

DEFAULT_SCRAPE_FORMATS: tuple[ScrapeFormat, ...] = ("markdown", "summary")

# Firecrawl renders the page before answering, which takes seconds, so the read timeout is generous
# while the connect timeout stays short: a connection that will not open is never worth waiting on.
DEFAULT_SCRAPE_TIMEOUT: tuple[float, float] = (5.0, 45.0)

SEARCH_ENDPOINT = "/v2/search"

DEFAULT_SEARCH_TIMEOUT: tuple[float, float] = (5.0, 45.0)

# Firecrawl bills search at 2 credits per 10 results, so an unbounded limit is an unbounded bill.
MAX_SEARCH_LIMIT = 10


class FirecrawlNotConfigured(Exception):
    """No Firecrawl API key is configured on this instance, so no call was made. Self-hosted
    deployments run without one, so callers must treat this as a normal degraded path."""


class FirecrawlScrapeFailed(Exception):
    """Firecrawl was reached but did not return a usable scrape (HTTP error, ``success: false``,
    or a body that does not match the documented shape)."""


class FirecrawlSearchFailed(Exception):
    """Firecrawl was reached but did not return a usable search (HTTP error, ``success: false``,
    or a body that does not match the documented shape)."""


@frozen
class FirecrawlScrape:
    """One scraped page. Every extracted field is optional: Firecrawl returns only the formats that
    were requested, and a page can render without a title or description."""

    url: str
    markdown: str | None = None
    summary: str | None = None
    title: str | None = None
    description: str | None = None
    status_code: int | None = None
    credits_used: int | None = None


@frozen
class FirecrawlSearchResult:
    """One web result from a Firecrawl search. Title and description are optional: Firecrawl does
    not guarantee either is present for every result."""

    url: str
    title: str | None = None
    description: str | None = None


@frozen
class FirecrawlSearch:
    """The results of one Firecrawl web search."""

    query: str
    results: tuple[FirecrawlSearchResult, ...]
    credits_used: int | None = None


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _as_mapping(value: object) -> Mapping[str, object] | None:
    # An isinstance check cannot narrow the key type, but these mappings come from a parsed JSON
    # body, where every key is a string by construction.
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else None


def _as_sequence(value: object) -> Sequence[object]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        return []
    return value


def scrape(
    url: str,
    *,
    source: str,
    formats: Sequence[ScrapeFormat] = DEFAULT_SCRAPE_FORMATS,
    only_main_content: bool = True,
    priority: Priority = Priority.NORMAL,
    timeout: float | tuple[float, float] = DEFAULT_SCRAPE_TIMEOUT,
) -> FirecrawlScrape:
    """Scrape one page through Firecrawl. Costs one credit per call regardless of how many formats
    are requested.

    Raises :class:`FirecrawlNotConfigured` when the instance has no API key,
    :class:`FirecrawlScrapeFailed` when Firecrawl answers with anything but a successful scrape, and
    :class:`~posthog.egress.firecrawl.transport.FirecrawlEgressBudgetExhausted` when our own egress
    budget sheds the call.
    """
    api_key = settings.FIRECRAWL_API_KEY
    if not api_key:
        raise FirecrawlNotConfigured("No FIRECRAWL_API_KEY configured")

    response = firecrawl_request(
        "POST",
        f"{FIRECRAWL_API_BASE}{SCRAPE_ENDPOINT}",
        api_key=api_key,
        source=source,
        endpoint=SCRAPE_ENDPOINT,
        priority=priority,
        timeout=timeout,
        json={"url": url, "formats": list(formats), "onlyMainContent": only_main_content},
    )

    if not response.ok:
        # The body can carry the scraped page, so keep it out of the exception that gets logged.
        raise FirecrawlScrapeFailed(f"Firecrawl scrape of {url} returned HTTP {response.status_code}")

    try:
        payload: object = response.json()
    except ValueError as exc:
        raise FirecrawlScrapeFailed(f"Firecrawl scrape of {url} returned a non-JSON body") from exc

    payload_mapping = _as_mapping(payload)
    if payload_mapping is None or payload_mapping.get("success") is not True:
        raise FirecrawlScrapeFailed(f"Firecrawl scrape of {url} was unsuccessful")

    data = _as_mapping(payload_mapping.get("data"))
    if data is None:
        raise FirecrawlScrapeFailed(f"Firecrawl scrape of {url} returned no data")

    metadata = _as_mapping(data.get("metadata")) or {}
    return FirecrawlScrape(
        url=url,
        markdown=_as_str(data.get("markdown")),
        summary=_as_str(data.get("summary")),
        title=_as_str(metadata.get("title")),
        description=_as_str(metadata.get("description")),
        status_code=_as_int(metadata.get("statusCode")),
        credits_used=_as_int(metadata.get("creditsUsed")),
    )


def search(
    query: str,
    *,
    source: str,
    limit: int = 5,
    priority: Priority = Priority.NORMAL,
    timeout: float | tuple[float, float] = DEFAULT_SEARCH_TIMEOUT,
) -> FirecrawlSearch:
    """Search the web through Firecrawl.

    Raises :class:`FirecrawlNotConfigured` when the instance has no API key,
    :class:`FirecrawlSearchFailed` when Firecrawl answers with anything but a successful search, and
    :class:`~posthog.egress.firecrawl.transport.FirecrawlEgressBudgetExhausted` when our own egress
    budget sheds the call.
    """
    if limit > MAX_SEARCH_LIMIT:
        raise ValueError(f"limit must be at most {MAX_SEARCH_LIMIT}")

    api_key = settings.FIRECRAWL_API_KEY
    if not api_key:
        raise FirecrawlNotConfigured("No FIRECRAWL_API_KEY configured")

    response = firecrawl_request(
        "POST",
        f"{FIRECRAWL_API_BASE}{SEARCH_ENDPOINT}",
        api_key=api_key,
        source=source,
        endpoint=SEARCH_ENDPOINT,
        priority=priority,
        timeout=timeout,
        json={"query": query, "limit": limit, "sources": [{"type": "web"}]},
    )

    if not response.ok:
        raise FirecrawlSearchFailed(f"Firecrawl search for {query!r} returned HTTP {response.status_code}")

    try:
        payload: object = response.json()
    except ValueError as exc:
        raise FirecrawlSearchFailed(f"Firecrawl search for {query!r} returned a non-JSON body") from exc

    payload_mapping = _as_mapping(payload)
    if payload_mapping is None or payload_mapping.get("success") is not True:
        raise FirecrawlSearchFailed(f"Firecrawl search for {query!r} was unsuccessful")

    data = _as_mapping(payload_mapping.get("data"))
    if data is None:
        raise FirecrawlSearchFailed(f"Firecrawl search for {query!r} returned no data")

    results = []
    for entry in _as_sequence(data.get("web")):
        entry_mapping = _as_mapping(entry)
        if entry_mapping is None:
            continue
        url = _as_str(entry_mapping.get("url"))
        if url is None:
            continue
        results.append(
            FirecrawlSearchResult(
                url=url,
                title=_as_str(entry_mapping.get("title")),
                description=_as_str(entry_mapping.get("description")),
            )
        )

    return FirecrawlSearch(
        query=query,
        results=tuple(results),
        credits_used=_as_int(payload_mapping.get("creditsUsed")),
    )
