"""Typed client for the one Firecrawl endpoint PostHog calls: a single-page scrape.

Firecrawl fetches and renders a page server-side and returns the extracted formats plus page
metadata. Only ``POST /v2/scrape`` is wired up; crawl, map and search are separate products with
their own credit cost and are not exposed until something needs them.
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


class FirecrawlNotConfigured(Exception):
    """No Firecrawl API key is configured on this instance, so no call was made. Self-hosted
    deployments run without one, so callers must treat this as a normal degraded path."""


class FirecrawlScrapeFailed(Exception):
    """Firecrawl was reached but did not return a usable scrape (HTTP error, ``success: false``,
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


def _as_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _as_mapping(value: object) -> Mapping[str, object] | None:
    # An isinstance check cannot narrow the key type, but these mappings come from a parsed JSON
    # body, where every key is a string by construction.
    return cast(Mapping[str, object], value) if isinstance(value, Mapping) else None


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
