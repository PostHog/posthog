"""Typed Firecrawl client for bounded public search and single-page scrapes.

Firecrawl fetches and renders a page server-side and returns the extracted formats plus page
metadata. Crawl and map are separate products with their own credit cost and are not exposed until
something needs them.
"""

import json
from collections.abc import Mapping, Sequence
from typing import Literal, cast
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings

import requests

from posthog.dataclasses import frozen
from posthog.egress.firecrawl.transport import firecrawl_request
from posthog.egress.limiter.policies import Priority
from posthog.security.url_validation import is_url_allowed

FIRECRAWL_API_BASE = "https://api.firecrawl.dev"
SCRAPE_ENDPOINT = "/v2/scrape"
SEARCH_ENDPOINT = "/v2/search"

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
MAX_FIRECRAWL_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_PUBLIC_RESEARCH_QUERY_LENGTH = 500
MAX_PUBLIC_RESEARCH_RESULTS = 3
MAX_PUBLIC_RESEARCH_URL_LENGTH = 2048
MAX_PUBLIC_RESEARCH_TITLE_LENGTH = 300
MAX_PUBLIC_RESEARCH_DESCRIPTION_LENGTH = 2000


class FirecrawlNotConfigured(Exception):
    """No Firecrawl API key is configured on this instance, so no call was made. Self-hosted
    deployments run without one, so callers must treat this as a normal degraded path."""


class FirecrawlRequestFailed(Exception):
    """Firecrawl was reached but its response could not be used."""


class FirecrawlScrapeFailed(FirecrawlRequestFailed):
    """Firecrawl was reached but did not return a usable scrape (HTTP error, ``success: false``,
    or a body that does not match the documented shape)."""


class FirecrawlSearchFailed(FirecrawlRequestFailed):
    """Firecrawl was reached but did not return a usable public-search response."""


class FirecrawlPublicTargetRejected(ValueError):
    """A target returned by Firecrawl is outside the public-research boundary."""


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
    """One bounded, public result from a Firecrawl web search."""

    url: str
    title: str | None = None
    description: str | None = None


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _as_mapping(value: object) -> Mapping[str, object] | None:
    # An isinstance check cannot narrow the key type, but these mappings come from a parsed JSON
    # body, where every key is a string by construction.
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else None


def _normalize_bounded_text(value: object, max_length: int) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value[:max_length].split())[:max_length] or None


def _validate_public_research_url(url: str) -> str:
    if not url or len(url) > MAX_PUBLIC_RESEARCH_URL_LENGTH or any(ord(character) < 32 for character in url):
        raise FirecrawlPublicTargetRejected("Public research URL exceeds its safe boundary")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise FirecrawlPublicTargetRejected("Public research URL is invalid") from exc

    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise FirecrawlPublicTargetRejected("Public research URL must be HTTP(S)")
    if parsed.username is not None or parsed.password is not None:
        raise FirecrawlPublicTargetRejected("Public research URL must not contain credentials")
    default_port = 443 if parsed.scheme == "https" else 80
    if port not in (None, default_port):
        raise FirecrawlPublicTargetRejected("Public research URL uses a non-standard port")

    allowed, _reason = is_url_allowed(url)
    if not allowed:
        raise FirecrawlPublicTargetRejected("Public research URL is not publicly accessible")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))


def _read_bounded_json_response(
    response: requests.Response,
    *,
    operation: str,
    failure_type: type[FirecrawlRequestFailed],
) -> object:
    try:
        if not response.ok:
            raise failure_type(f"{operation} returned HTTP {response.status_code}")

        content_length = response.headers.get("Content-Length")
        if content_length is not None and (
            not content_length.isdigit() or int(content_length) > MAX_FIRECRAWL_RESPONSE_BYTES
        ):
            raise failure_type(f"{operation} exceeded its response budget")

        body = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            body.extend(chunk)
            if len(body) > MAX_FIRECRAWL_RESPONSE_BYTES:
                raise failure_type(f"{operation} exceeded its response budget")
        return json.loads(body)
    except (UnicodeDecodeError, ValueError) as exc:
        raise failure_type(f"{operation} returned a non-JSON body") from exc
    except requests.RequestException as exc:
        raise failure_type(f"{operation} could not be read") from exc
    finally:
        response.close()


def scrape(
    url: str,
    *,
    source: str,
    formats: Sequence[ScrapeFormat] = DEFAULT_SCRAPE_FORMATS,
    only_main_content: bool = True,
    priority: Priority = Priority.NORMAL,
    timeout: float | tuple[float, float] = DEFAULT_SCRAPE_TIMEOUT,
    lockdown: bool = False,
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

    try:
        request_body: dict[str, object] = {
            "url": url,
            "formats": list(formats),
            "onlyMainContent": only_main_content,
        }
        if lockdown:
            request_body["lockdown"] = True
        response = firecrawl_request(
            "POST",
            f"{FIRECRAWL_API_BASE}{SCRAPE_ENDPOINT}",
            api_key=api_key,
            source=source,
            endpoint=SCRAPE_ENDPOINT,
            priority=priority,
            timeout=timeout,
            json=request_body,
            stream=True,
        )
    except requests.RequestException as exc:
        raise FirecrawlScrapeFailed("Firecrawl scrape could not connect") from exc

    payload = _read_bounded_json_response(
        response,
        operation="Firecrawl scrape",
        failure_type=FirecrawlScrapeFailed,
    )

    payload_mapping = _as_mapping(payload)
    if payload_mapping is None or payload_mapping.get("success") is not True:
        raise FirecrawlScrapeFailed(f"Firecrawl scrape of {url} was unsuccessful")

    data = _as_mapping(payload_mapping.get("data"))
    if data is None:
        raise FirecrawlScrapeFailed(f"Firecrawl scrape of {url} returned no data")

    metadata = _as_mapping(data.get("metadata")) or {}
    return FirecrawlScrape(
        url=_as_str(metadata.get("url")) or _as_str(metadata.get("sourceURL")) or url,
        markdown=_as_str(data.get("markdown")),
        summary=_as_str(data.get("summary")),
        title=_as_str(metadata.get("title")),
        description=_as_str(metadata.get("description")),
        status_code=_as_int(metadata.get("statusCode")),
        credits_used=_as_int(metadata.get("creditsUsed")),
    )


def search_public_web(
    query: str,
    *,
    source: str,
    priority: Priority = Priority.NORMAL,
    timeout: float | tuple[float, float] = DEFAULT_SCRAPE_TIMEOUT,
) -> tuple[FirecrawlSearchResult, ...]:
    """Search the public web through Firecrawl and return at most three validated results."""
    api_key = settings.FIRECRAWL_API_KEY
    if not api_key:
        raise FirecrawlNotConfigured("No FIRECRAWL_API_KEY configured")
    if not query or len(query) > MAX_PUBLIC_RESEARCH_QUERY_LENGTH or any(ord(character) < 32 for character in query):
        raise FirecrawlPublicTargetRejected("Public research query exceeds its safe boundary")

    try:
        response = firecrawl_request(
            "POST",
            f"{FIRECRAWL_API_BASE}{SEARCH_ENDPOINT}",
            api_key=api_key,
            source=source,
            endpoint=SEARCH_ENDPOINT,
            priority=priority,
            timeout=timeout,
            json={"query": query, "limit": MAX_PUBLIC_RESEARCH_RESULTS, "sources": ["web"]},
            stream=True,
        )
    except requests.RequestException as exc:
        raise FirecrawlSearchFailed("Firecrawl search could not connect") from exc

    payload = _read_bounded_json_response(
        response,
        operation="Firecrawl search",
        failure_type=FirecrawlSearchFailed,
    )
    payload_mapping = _as_mapping(payload)
    data = (
        _as_mapping(payload_mapping.get("data")) if payload_mapping and payload_mapping.get("success") is True else None
    )
    web_results = data.get("web") if data else None
    if not isinstance(web_results, Sequence) or isinstance(web_results, (str, bytes, bytearray)):
        raise FirecrawlSearchFailed("Firecrawl search returned no web results")

    results: list[FirecrawlSearchResult] = []
    for value in web_results[:MAX_PUBLIC_RESEARCH_RESULTS]:
        item = _as_mapping(value)
        if item is None:
            continue
        raw_url = _as_str(item.get("url"))
        if raw_url is None:
            continue
        try:
            url = _validate_public_research_url(raw_url)
        except FirecrawlPublicTargetRejected:
            continue
        results.append(
            FirecrawlSearchResult(
                url=url,
                title=_normalize_bounded_text(item.get("title"), MAX_PUBLIC_RESEARCH_TITLE_LENGTH),
                description=_normalize_bounded_text(item.get("description"), MAX_PUBLIC_RESEARCH_DESCRIPTION_LENGTH),
            )
        )
    return tuple(results)


def scrape_public_url(
    url: str,
    *,
    source: str,
    priority: Priority = Priority.NORMAL,
    timeout: float | tuple[float, float] = DEFAULT_SCRAPE_TIMEOUT,
) -> FirecrawlScrape:
    """Scrape a validated public result and reject a provider-reported redirect escape."""
    requested_url = _validate_public_research_url(url)
    result = scrape(
        requested_url,
        source=source,
        formats=("markdown",),
        priority=priority,
        timeout=timeout,
        lockdown=True,
    )
    _validate_public_research_url(result.url)
    return result
