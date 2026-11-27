"""The docs library: the business knowledge library that holds the PostHog documentation.

One project holds the library, and every region and every customer project searches it. The search is
therefore an HTTP call with a project secret API key, and not a query on the caller's own team.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import urlsplit

from django.conf import settings

import httpx
import structlog

from posthog.ph_client import feature_enabled_or_false

from .facade.contracts import DocsPage

logger = structlog.get_logger(__name__)

DOCS_LIBRARY_FLAG = "docs-search-business-knowledge-library"
DOCS_LIBRARY_TIMEOUT = httpx.Timeout(4.0, connect=2.0)
DOCS_LIBRARY_RESULT_LIMIT = 10
# Every customer reads what the library returns. A source that someone adds to the library by mistake
# can hold internal pages, so a result on any other host is dropped. Subdomains are not accepted,
# because some of them serve internal sites.
_PUBLIC_DOCS_HOSTS = frozenset({"posthog.com", "www.posthog.com"})
# All organizations share the one key, and so the one rate limit. After a throttled response, this
# process sends no request until the wait ends, so a throttled library costs no extra round trip.
_DEFAULT_THROTTLE_WAIT_SECONDS = 60.0
_MAX_THROTTLE_WAIT_SECONDS = 300.0
_throttled_until = 0.0


def is_docs_library_configured() -> bool:
    return bool(
        settings.DOCS_SEARCH_LIBRARY_API_KEY
        and settings.DOCS_SEARCH_LIBRARY_HOST
        and settings.DOCS_SEARCH_LIBRARY_PROJECT_ID
        and settings.DOCS_SEARCH_LIBRARY_ID
    )


def has_docs_library_feature_flag(organization_id: str) -> bool:
    """Org-keyed. On in DEBUG, where the four settings are the opt-in."""
    if settings.DEBUG:
        return True
    # Local evaluation only. A remote lookup would run on every docs search.
    return feature_enabled_or_false(
        DOCS_LIBRARY_FLAG,
        organization_id,
        groups={"organization": organization_id},
        group_properties={"organization": {"id": organization_id}},
        only_evaluate_locally=True,
        send_feature_flag_events=False,
    )


def _is_public_docs_url(url: str) -> bool:
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return False
    return parsed.scheme == "https" and (parsed.hostname or "").lower() in _PUBLIC_DOCS_HOSTS


def pages_from_results(rows: list[Any]) -> list[DocsPage]:
    """Group search result chunks into one page per document, best document first."""
    chunks_by_document: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        url = row.get("url")
        document_id = row.get("document_id")
        if not isinstance(url, str) or not isinstance(document_id, str) or not _is_public_docs_url(url):
            continue
        chunks_by_document.setdefault(document_id, []).append(row)

    pages: list[DocsPage] = []
    for chunks in chunks_by_document.values():
        chunks.sort(key=lambda chunk: chunk.get("ordinal") or 0)
        text = "\n\n".join(str(chunk.get("content") or "").strip() for chunk in chunks).strip()
        if not text:
            continue
        first = chunks[0]
        pages.append(
            DocsPage(
                title=str(first.get("document_title") or first.get("heading_path") or "Untitled"),
                url=str(first["url"]).strip(),
                text=text,
            )
        )
    return pages


def _throttle_wait_seconds(response: httpx.Response) -> float:
    try:
        wait = float(response.headers.get("Retry-After", ""))
    except ValueError:
        return _DEFAULT_THROTTLE_WAIT_SECONDS
    return min(max(wait, 1.0), _MAX_THROTTLE_WAIT_SECONDS)


async def fetch_docs_library_pages(query: str, *, transport: httpx.AsyncBaseTransport | None = None) -> list[DocsPage]:
    url = (
        f"{settings.DOCS_SEARCH_LIBRARY_HOST}/api/projects/{settings.DOCS_SEARCH_LIBRARY_PROJECT_ID}"
        "/business_knowledge/documents/search/"
    )
    async with httpx.AsyncClient(timeout=DOCS_LIBRARY_TIMEOUT, transport=transport) as client:
        # POST, because the receiving side logs request URLs, and the query can hold what a customer pasted.
        response = await client.post(
            url,
            json={
                "query": query,
                "limit": DOCS_LIBRARY_RESULT_LIMIT,
                # A key with no library limit reads the whole project. The explicit id keeps such a key on the docs library.
                "library_id": settings.DOCS_SEARCH_LIBRARY_ID,
            },
            headers={"Authorization": f"Bearer {settings.DOCS_SEARCH_LIBRARY_API_KEY}"},
        )
    if response.status_code == 429:
        global _throttled_until
        _throttled_until = time.monotonic() + _throttle_wait_seconds(response)
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list):
        raise ValueError("The docs library search did not return a list.")
    return pages_from_results(rows)


async def search_docs_library(
    query: str, *, organization_id: str, transport: httpx.AsyncBaseTransport | None = None
) -> list[DocsPage]:
    """Pages for `query` from the docs library. An empty list tells the caller to use its other docs search."""
    if not is_docs_library_configured() or not has_docs_library_feature_flag(organization_id):
        return []
    if time.monotonic() < _throttled_until:
        return []
    try:
        pages = await fetch_docs_library_pages(query, transport=transport)
    except Exception as error:
        # The exception text holds the request URL, which carries the caller's query, so it stays out of the log.
        response = getattr(error, "response", None)
        logger.warning(
            "docs_library_search_failed",
            error_type=type(error).__name__,
            status_code=getattr(response, "status_code", None),
        )
        return []
    if not pages:
        logger.info("docs_library_search_empty")
    return pages
