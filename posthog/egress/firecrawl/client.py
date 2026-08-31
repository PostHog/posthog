"""Typed Firecrawl client for bounded scrapes and reviewed-domain metadata search.

Public research searches only server-reviewed domains without scraping results, then retrieves an
eligible page through Firecrawl's cache-only scrape mode. Crawl, map, and content-bearing search
remain outside this client.
"""

import json
import socket
import ipaddress
from collections.abc import Mapping, Sequence
from typing import Literal, cast
from urllib.parse import urlsplit, urlunsplit

from django.conf import settings

import requests

from posthog.dataclasses import frozen
from posthog.egress.firecrawl.transport import firecrawl_request
from posthog.egress.limiter.policies import Priority

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
MAX_PUBLIC_TARGET_URL_LENGTH = 2048
MAX_PUBLIC_SEARCH_RESULTS = 5


class FirecrawlNotConfigured(Exception):
    """No Firecrawl API key is configured on this instance, so no call was made. Self-hosted
    deployments run without one, so callers must treat this as a normal degraded path."""


class FirecrawlRequestFailed(Exception):
    pass


class FirecrawlScrapeFailed(FirecrawlRequestFailed):
    """Firecrawl was reached but did not return a usable scrape (HTTP error, ``success: false``,
    or a body that does not match the documented shape)."""


class FirecrawlSearchFailed(FirecrawlRequestFailed):
    """Firecrawl did not return a usable bounded public-search response."""


class FirecrawlPublicTargetRejected(ValueError):
    """A requested public-research target is outside its reviewed network boundary."""


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


def _normalized_host(hostname: str) -> str:
    try:
        return hostname.rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise FirecrawlPublicTargetRejected("Public research URL has an invalid hostname") from exc


def _is_allowed_domain(hostname: str, allowed_domains: Sequence[str]) -> bool:
    return any(hostname == domain or hostname.endswith(f".{domain}") for domain in allowed_domains)


def _validate_public_target_url(url: str, *, allowed_domains: Sequence[str]) -> str:
    if len(url) > MAX_PUBLIC_TARGET_URL_LENGTH or any(ord(character) < 32 for character in url):
        raise FirecrawlPublicTargetRejected("Public research URL exceeds its safe boundary")
    allowed = tuple(_normalized_host(domain) for domain in allowed_domains if domain)
    if not allowed:
        raise FirecrawlPublicTargetRejected("Public research has no reviewed result domains")

    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password:
        raise FirecrawlPublicTargetRejected("Public research URL must be an unauthenticated HTTP(S) URL")
    try:
        port = parsed.port
    except ValueError as exc:
        raise FirecrawlPublicTargetRejected("Public research URL has an invalid port") from exc
    expected_port = 443 if parsed.scheme == "https" else 80
    if port not in (None, expected_port):
        raise FirecrawlPublicTargetRejected("Public research URL uses a non-standard port")

    hostname = _normalized_host(parsed.hostname)
    if not _is_allowed_domain(hostname, allowed):
        raise FirecrawlPublicTargetRejected("Public research URL is outside reviewed result domains")

    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            answers = socket.getaddrinfo(hostname, expected_port, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise FirecrawlPublicTargetRejected("Public research URL could not be resolved") from exc
        if not answers:
            raise FirecrawlPublicTargetRejected("Public research URL could not be resolved")
        addresses = [ipaddress.ip_address(answer[4][0]) for answer in answers]
    else:
        addresses = [literal_ip]
    if any(not address.is_global for address in addresses):
        raise FirecrawlPublicTargetRejected("Public research URL resolves to a non-public address")

    return urlunsplit((parsed.scheme, hostname, parsed.path or "/", parsed.query, ""))


def _read_bounded_json_response(
    response: requests.Response,
    *,
    operation: str,
    failure_type: type[FirecrawlRequestFailed],
) -> object:
    if not response.ok:
        response.close()
        raise failure_type(f"{operation} returned HTTP {response.status_code}")
    try:
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

    request_body: dict[str, object] = {
        "url": url,
        "formats": list(formats),
        "onlyMainContent": only_main_content,
    }
    if lockdown:
        request_body["lockdown"] = True
    try:
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
        url=_as_str(metadata.get("sourceURL")) or _as_str(metadata.get("url")) or url,
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
    allowed_domains: Sequence[str],
    limit: int = 3,
    priority: Priority = Priority.NORMAL,
    timeout: float | tuple[float, float] = DEFAULT_SCRAPE_TIMEOUT,
) -> tuple[FirecrawlSearchResult, ...]:
    """Search reviewed public domains without asking Firecrawl to scrape the result pages."""
    api_key = settings.FIRECRAWL_API_KEY
    if not api_key:
        raise FirecrawlNotConfigured("No FIRECRAWL_API_KEY configured")
    if not query or len(query) > 512 or any(ord(character) < 32 for character in query):
        raise FirecrawlPublicTargetRejected("Public research query exceeds its safe boundary")
    if limit < 1 or limit > MAX_PUBLIC_SEARCH_RESULTS:
        raise FirecrawlPublicTargetRejected("Public research result limit exceeds its safe boundary")
    reviewed_domains = tuple(dict.fromkeys(_normalized_host(domain) for domain in allowed_domains if domain))
    if not reviewed_domains:
        raise FirecrawlPublicTargetRejected("Public research has no reviewed result domains")

    try:
        response = firecrawl_request(
            "POST",
            f"{FIRECRAWL_API_BASE}{SEARCH_ENDPOINT}",
            api_key=api_key,
            source=source,
            endpoint=SEARCH_ENDPOINT,
            priority=priority,
            timeout=timeout,
            json={
                "query": query,
                "limit": limit,
                "sources": ["web"],
                "includeDomains": list(reviewed_domains),
            },
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
    for value in web_results[:limit]:
        item = _as_mapping(value)
        if item is None:
            continue
        raw_url = _as_str(item.get("url"))
        if raw_url is None:
            continue
        try:
            url = _validate_public_target_url(raw_url, allowed_domains=reviewed_domains)
        except FirecrawlPublicTargetRejected:
            continue
        raw_title = _as_str(item.get("title"))
        raw_description = _as_str(item.get("description"))
        title = " ".join((raw_title or "")[:1200].split())[:300] or None
        description = " ".join((raw_description or "")[:8000].split())[:2000] or None
        results.append(FirecrawlSearchResult(url=url, title=title, description=description))
    return tuple(results)


def scrape_public_url(
    url: str,
    *,
    source: str,
    allowed_domains: Sequence[str],
) -> FirecrawlScrape:
    """Scrape one reviewed public URL with DNS, host, and final-redirect validation.

    The server-owned caller supplies the reviewed domain list. The model never controls
    either that list or the provider credentials. Firecrawl's final canonical URL is
    validated again before its content can enter a Pulse evidence record.
    """
    requested_url = _validate_public_target_url(url, allowed_domains=allowed_domains)
    result = scrape(requested_url, source=source, formats=("markdown",), lockdown=True)
    _validate_public_target_url(result.url, allowed_domains=allowed_domains)
    return result
