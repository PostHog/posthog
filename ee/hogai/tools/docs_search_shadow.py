"""Compare an Inkeep docs result with this team's business knowledge search.

The Inkeep payload is what callers format and return. The business knowledge
search runs beside it and can never change that payload.
"""

from __future__ import annotations

import time
import asyncio
from collections.abc import Awaitable, Callable
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import structlog
import posthoganalytics

from posthog.dataclasses import frozen
from posthog.event_usage import groups
from posthog.models.team.team import Team

from products.business_knowledge.backend.logic import (
    KnowledgeSearchResult,
    async_search_knowledge_for_team,
    has_docs_shadow_feature_flag,
)

from ee.hogai.tools.search import is_community_question_url

logger = structlog.get_logger(__name__)

SHADOW_EVENT = "business knowledge docs shadow"
SHADOW_TIMEOUT_SECONDS = 3.0
DocsShadowSurface = Literal["mcp", "posthog_ai"]


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


def _swallow_task_outcome(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    # Retrieve the exception so a finished task does not warn about it later.
    task.exception()


def _abandon(task: asyncio.Task) -> None:
    """Drop a task without waiting for it.

    `database_sync_to_async` shields its worker thread and, on cancellation, waits
    for that thread to finish. Awaiting the cancel would hold the Inkeep response
    for the whole search.
    """
    if task.done():
        _swallow_task_outcome(task)
        return
    task.add_done_callback(_swallow_task_outcome)
    task.cancel()


async def _bounded_bk_search(team: Team, query: str) -> tuple[list[str], str | None, float]:
    started = time.perf_counter()
    # `wait_for` cannot preempt `database_sync_to_async`: cancellation is shielded
    # and then awaited, so the timeout would not apply to the query itself.
    search_task = asyncio.create_task(async_search_knowledge_for_team(team, query))
    try:
        done, _pending = await asyncio.wait({search_task}, timeout=SHADOW_TIMEOUT_SECONDS)
    except asyncio.CancelledError:
        _abandon(search_task)
        raise
    elapsed_ms = (time.perf_counter() - started) * 1000
    if search_task not in done:
        _abandon(search_task)
        return [], "timeout", elapsed_ms
    try:
        results = search_task.result()
    except Exception:
        logger.warning("bk_docs_shadow_search_failed", team_id=team.id, exc_info=True)
        return [], "exception", elapsed_ms
    return _urls_from_results(results), None, elapsed_ms


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
            "inkeep_urls": comparison.inkeep_urls,
            "bk_urls": comparison.bk_urls,
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
    return payload, (time.perf_counter() - started) * 1000


async def _finish_shadow(
    *,
    team: Team,
    query: str,
    surface: DocsShadowSurface,
    payload: dict | None,
    bk_task: asyncio.Task[tuple[list[str], str | None, float]],
    inkeep_latency_ms: float,
) -> None:
    """Record the comparison. Failures here must not change the Inkeep payload."""
    try:
        bk_urls, bk_error, bk_latency_ms = await bk_task
        comparison = compare_docs_results(inkeep_result_urls(payload), bk_urls)
        _capture_shadow(
            team=team,
            query=query,
            surface=surface,
            comparison=comparison,
            inkeep_latency_ms=inkeep_latency_ms,
            bk_latency_ms=bk_latency_ms,
            bk_error=bk_error,
        )
    except Exception:
        logger.warning("bk_docs_shadow_capture_failed", team_id=team.id, exc_info=True)


async def fetch_inkeep_with_shadow(
    *,
    team: Team,
    query: str,
    fetch_inkeep: Callable[[], Awaitable[dict | None]],
    surface: DocsShadowSurface,
) -> dict | None:
    """Run Inkeep and, when the shadow flag is on, a business knowledge search beside it."""
    inkeep_task = asyncio.create_task(_timed_inkeep(fetch_inkeep))
    bk_task: asyncio.Task[tuple[list[str], str | None, float]] | None = None
    try:
        try:
            enabled = has_docs_shadow_feature_flag(team)
        except Exception:
            logger.warning("bk_docs_shadow_flag_failed", team_id=team.id, exc_info=True)
            enabled = False
        if enabled:
            bk_task = asyncio.create_task(_bounded_bk_search(team, query))
        payload, inkeep_latency_ms = await inkeep_task
        if bk_task is not None:
            await _finish_shadow(
                team=team,
                query=query,
                surface=surface,
                payload=payload,
                bk_task=bk_task,
                inkeep_latency_ms=inkeep_latency_ms,
            )
        return payload
    except BaseException:
        _abandon(inkeep_task)
        if bk_task is not None:
            _abandon(bk_task)
        raise
