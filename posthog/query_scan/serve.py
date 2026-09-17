"""Put the stored analysis on a summary, on a cache hit and on a fresh run alike.

A summary that asked for an analysis says so, and that alone decides whether the slot is read; the
cached copy of the summary is never rewritten. A Redis failure drops the advice, never the results.
"""

from __future__ import annotations

from typing import Any

import structlog

from posthog.schema import QueryScanAnalysis, QueryScanSummary

from posthog.clickhouse.query_tagging import get_query_tag_value, is_api_key_access_method
from posthog.models.team.team import Team
from posthog.query_scan.findings import assistant_prompt
from posthog.query_scan.flag import QueryScanMode, get_query_scan_flag
from posthog.query_scan.slot import get as get_slot
from posthog.query_scan.trigger import is_mcp_run

logger = structlog.get_logger(__name__)


def hydrate_response_scan(team: Team, response: Any) -> None:
    """Put the stored analysis on an outgoing query response, or take the summary off when the flag no
    longer shows findings."""
    try:
        summary = getattr(response, "query_scan", None)
        if summary is None:
            return
        response.query_scan = hydrate(team, summary, getattr(response, "cache_key", None))
    except Exception:
        logger.warning("query_scan_hydrate_failed", team_id=team.pk, exc_info=True)


def hydrate_scan_summary(team: Team, summary: dict[str, Any], cache_key: str | None) -> dict[str, Any] | None:
    """The same for a surface of plain dicts, such as an insight's stored result. None when the flag no
    longer shows findings, and when the summary cannot be read."""
    try:
        hydrated = hydrate(team, QueryScanSummary.model_validate(summary), cache_key)
        if hydrated is None:
            return None
        return hydrated.model_dump(mode="json", by_alias=True, exclude_none=True)
    except Exception:
        logger.warning("query_scan_hydrate_failed", team_id=team.pk, exc_info=True)
        return None


def hydrate(team: Team, summary: QueryScanSummary, cache_key: str | None) -> QueryScanSummary | None:
    """``summary`` with its stored analysis on it, or None when the flag no longer shows findings. The
    flag is evaluated locally, so a summary that asked for nothing costs no round trip."""
    flag = get_query_scan_flag(team)
    if flag is None or flag.mode != QueryScanMode.SHOW:
        return None
    if not summary.analysis_requested or cache_key is None:
        return summary
    slot = get_slot(team.pk, cache_key, thresholds=flag.thresholds_fingerprint)
    if slot is None or slot.analysis is None:
        return summary
    summary.analysis = analysis_with_prompt(
        slot.analysis, rows_read=summary.rows_read, duration_ms=summary.duration_ms, killed=bool(summary.killed)
    )
    return summary


def analysis_with_prompt(
    analysis: QueryScanAnalysis, *, rows_read: int | None = None, duration_ms: int | None = None, killed: bool = False
) -> QueryScanAnalysis:
    """The analysis with its prompt, built here so no client keeps its own copy. The run facts
    describe the run being served, not the run the analysis came from.

    A person in the app reaches the prompt through "Fix with AI", so theirs holds only what the
    assistant can change in the query. An API key or the MCP server runs the query for an agent,
    which reads the prompt itself, so that one covers every finding.
    """
    reader_is_an_agent = is_api_key_access_method(get_query_tag_value("access_method")) or is_mcp_run()
    prompt = assistant_prompt(
        list(analysis.findings),
        rows_read=rows_read,
        duration_ms=duration_ms,
        range_share=analysis.range_share,
        project_share=analysis.project_share,
        killed=killed,
        fixable_only=not reader_is_an_agent,
    )
    return analysis.model_copy(update={"assistant_prompt": prompt})
