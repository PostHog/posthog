"""Compare an Inkeep docs result with this team's business knowledge search.

The Inkeep payload is what callers format and return. The business knowledge
search runs beside it and can never change that payload.
"""

from __future__ import annotations

import time
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

from django.db import close_old_connections

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.models.team.team import Team

from products.business_knowledge.backend.logic import (
    KnowledgeSearchResult,
    RetrievalTrace,
    has_docs_shadow_feature_flag,
    search_knowledge_for_team,
)

from ee.hogai.tools.search import is_community_question_url

logger = structlog.get_logger(__name__)

SHADOW_EVENT = "business knowledge docs shadow"
# A search slower than this is recorded as a timeout, and its URLs are not compared.
SHADOW_TIMEOUT_SECONDS = 3.0
# Inkeep returns public PostHog docs. URLs on other hosts come from the team's own crawled
# sources and can carry tokens or private identifiers in their paths, so the event only counts them.
_PUBLIC_DOCS_HOSTS = frozenset({"posthog.com"})
_MAX_IN_FLIGHT_SEARCHES = 4
DocsShadowSurface = Literal["mcp", "posthog_ai"]


@frozen
class _ShadowSearch:
    urls: list[str]
    error: Literal["timeout", "exception"] | None
    latency_ms: float


@frozen
class _PendingSearch:
    future: Future[_ShadowSearch]


@frozen
class DocsShadowComparison:
    inkeep_urls: list[str]
    bk_urls: list[str]
    overlap_count: int
    recall_at_k: float | None
    top1_match: bool
    inkeep_count: int
    bk_count: int


def normalize_doc_url(url: str) -> str:
    """Lowercase the host, drop www, and strip the query, fragment, and trailing slash."""
    try:
        parsed = urlsplit(url.strip())
        # Out-of-range ports raise ValueError. Drop the URL instead of failing the comparison.
        port = parsed.port
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    default_port = (parsed.scheme == "http" and port == 80) or (parsed.scheme == "https" and port == 443)
    netloc = host if port is None or default_port else f"{host}:{port}"
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))


def inkeep_result_urls(payload: dict | None) -> list[str]:
    """Document URLs from an Inkeep payload, with community questions removed."""
    if not isinstance(payload, dict):
        return []
    content = payload.get("content")
    if not isinstance(content, list):
        return []
    urls: list[str] = []
    for doc in content:
        if not isinstance(doc, dict) or doc.get("type") != "document":
            continue
        url = doc.get("url")
        if not isinstance(url, str) or not url or is_community_question_url(url):
            continue
        urls.append(url)
    return urls


def _unique_normalized(urls: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for url in urls:
        normalized = normalize_doc_url(url)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique.append(normalized)
    return unique


def compare_docs_results(inkeep_urls: list[str], bk_urls: list[str]) -> DocsShadowComparison:
    inkeep = _unique_normalized(inkeep_urls)
    bk = _unique_normalized(bk_urls)
    overlap_count = len(set(inkeep) & set(bk))
    return DocsShadowComparison(
        inkeep_urls=inkeep,
        bk_urls=bk,
        overlap_count=overlap_count,
        recall_at_k=(overlap_count / len(inkeep)) if inkeep else None,
        top1_match=bool(inkeep and bk and inkeep[0] == bk[0]),
        inkeep_count=len(inkeep),
        bk_count=len(bk),
    )


def _urls_from_results(results: list[KnowledgeSearchResult]) -> list[str]:
    return [result.url for result in results if result.url]


def _public_docs_urls(normalized_urls: list[str]) -> list[str]:
    public: list[str] = []
    for url in normalized_urls:
        host = (urlsplit(url).hostname or "").lower()
        if host in _PUBLIC_DOCS_HOSTS or any(host.endswith(f".{public_host}") for public_host in _PUBLIC_DOCS_HOSTS):
            public.append(url)
    return public


# The search runs on these threads and not on the caller's event loop. `async_to_sync`
# callers end their loop with `asyncio.run`, which waits for every pending task, so a
# search on that loop holds the docs response until the search finishes.
_shadow_executor = ThreadPoolExecutor(max_workers=_MAX_IN_FLIGHT_SEARCHES, thread_name_prefix="bk-docs-shadow")
# A slow search keeps its thread and its database connection until it finishes. A search
# starts only when a slot is free, so slow searches cannot pile up.
_search_slots = threading.BoundedSemaphore(_MAX_IN_FLIGHT_SEARCHES)


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def _run_search(team: Team, query: str, started: float) -> _ShadowSearch:
    try:
        results = search_knowledge_for_team(team, query, trace=RetrievalTrace(surface="docs_shadow"))
    except Exception:
        logger.warning("bk_docs_shadow_search_failed", team_id=team.id, exc_info=True)
        return _ShadowSearch(urls=[], error="exception", latency_ms=_elapsed_ms(started))
    finally:
        # The executor threads live for the whole process, and no request cycle closes their connections.
        close_old_connections()
    latency_ms = _elapsed_ms(started)
    if latency_ms > SHADOW_TIMEOUT_SECONDS * 1000:
        return _ShadowSearch(urls=[], error="timeout", latency_ms=latency_ms)
    return _ShadowSearch(urls=_urls_from_results(results), error=None, latency_ms=latency_ms)


def _start_search(team: Team, query: str) -> _PendingSearch | None:
    if not _search_slots.acquire(blocking=False):
        return None
    try:
        future = _shadow_executor.submit(_run_search, team, query, time.perf_counter())
    except BaseException:
        _search_slots.release()
        raise
    future.add_done_callback(lambda _future: _search_slots.release())
    return _PendingSearch(future=future)


def _capture_shadow(
    *,
    team: Team,
    query: str,
    surface: DocsShadowSurface,
    comparison: DocsShadowComparison,
    inkeep_latency_ms: float,
    bk_latency_ms: float,
    bk_error: str | None,
) -> None:
    posthoganalytics.capture(
        distinct_id=str(team.uuid),
        event=SHADOW_EVENT,
        properties={
            "surface": surface,
            "query_length": len(query),
            "inkeep_urls": _public_docs_urls(comparison.inkeep_urls),
            "bk_urls": _public_docs_urls(comparison.bk_urls),
            "overlap_count": comparison.overlap_count,
            "recall_at_k": comparison.recall_at_k,
            "top1_match": comparison.top1_match,
            "inkeep_count": comparison.inkeep_count,
            "bk_count": comparison.bk_count,
            "inkeep_latency_ms": inkeep_latency_ms,
            "bk_latency_ms": bk_latency_ms,
            "bk_error": bk_error,
        },
        groups=groups(team=team),
    )


async def _timed_inkeep(fetch_inkeep: Callable[[], Awaitable[dict | None]]) -> tuple[dict | None, float]:
    started = time.perf_counter()
    payload = await fetch_inkeep()
    return payload, _elapsed_ms(started)


def _record_when_done(
    *,
    team: Team,
    query: str,
    surface: DocsShadowSurface,
    payload: dict | None,
    pending: _PendingSearch,
    inkeep_latency_ms: float,
) -> None:
    """Record the comparison when the search finishes. Failures here must not change the Inkeep payload."""

    def record(future: Future[_ShadowSearch]) -> None:
        try:
            search = future.result()
            comparison = compare_docs_results(inkeep_result_urls(payload), search.urls)
            _capture_shadow(
                team=team,
                query=query,
                surface=surface,
                comparison=comparison,
                inkeep_latency_ms=inkeep_latency_ms,
                bk_latency_ms=search.latency_ms,
                bk_error=search.error,
            )
        except Exception:
            logger.warning("bk_docs_shadow_capture_failed", team_id=team.id, exc_info=True)

    pending.future.add_done_callback(record)


async def fetch_inkeep_with_shadow(
    *,
    team: Team,
    query: str,
    fetch_inkeep: Callable[[], Awaitable[dict | None]],
    surface: DocsShadowSurface,
) -> dict | None:
    """Run Inkeep and, when the shadow flag is on, a business knowledge search beside it.

    The Inkeep payload returns as soon as Inkeep does. The comparison is recorded later, from the search thread.
    """
    pending: _PendingSearch | None = None
    try:
        if has_docs_shadow_feature_flag(team):
            pending = _start_search(team, query)
    except Exception:
        logger.warning("bk_docs_shadow_start_failed", team_id=team.id, exc_info=True)
    payload, inkeep_latency_ms = await _timed_inkeep(fetch_inkeep)
    if pending is not None:
        _record_when_done(
            team=team,
            query=query,
            surface=surface,
            payload=payload,
            pending=pending,
            inkeep_latency_ms=inkeep_latency_ms,
        )
    return payload
