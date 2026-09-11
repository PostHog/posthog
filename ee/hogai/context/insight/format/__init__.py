import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from posthog.schema import (
    AssistantFunnelsQuery,
    AssistantHogQLQuery,
    AssistantLifecycleQuery,
    AssistantPathsQuery,
    AssistantRetentionQuery,
    AssistantStickinessQuery,
    AssistantTrendsQuery,
    ChartDisplayType,
    DataTableNode,
    DataVisualizationNode,
    FunnelsQuery,
    HogQLQuery,
    InsightVizNode,
    LifecycleQuery,
    PathsQuery,
    RetentionQuery,
    StickinessQuery,
    TrendsQuery,
)

from posthog.query_scan.findings import ASSISTANT_GOAL, ASSISTANT_RULES, format_rows, format_seconds
from posthog.query_scan.flag import DEFAULT_FLOOR_MS, get_query_scan_flag

from .boxplot import BoxPlotResultsFormatter
from .funnel import FunnelResultsFormatter
from .lifecycle import LifecycleResultsFormatter
from .paths import PathsResultsFormatter
from .retention import RetentionResultsFormatter
from .sql import NULL_MARKER, TRUNCATED_MARKER, SQLResultsFormatter
from .stickiness import StickinessResultsFormatter
from .trends import TrendsResultsFormatter

if TYPE_CHECKING:
    from posthog.models import Team


def is_boxplot_query(query: BaseModel) -> bool:
    trends_filter = getattr(query, "trendsFilter", None)
    return trends_filter is not None and getattr(trends_filter, "display", None) == ChartDisplayType.BOX_PLOT


def get_boxplot_results(response: dict[str, Any]) -> list[Any]:
    # TODO: remove boxplot_data fallback once cached responses have rotated (added 2026-04-17)
    results = response.get("results", [])
    return results if results else response.get("boxplot_data", [])


# A message can carry event names that anyone capturing events controls, and it goes verbatim
# into agent context. Strip control characters and cap the length to keep them contained as data.
_UNSAFE_WARNING_CHARS = re.compile(r"[\x00-\x1f\x7f]")
# Dropping every angle bracket stops a crafted name (for example one containing
# `</taxonomy_warnings>`) from closing the wrapper early and breaking out of the delimited block.
_ANGLE_BRACKETS = re.compile(r"[<>]")
# A line PostHog composes carries operators but no project data, so only the shapes that could
# close a wrapper go, repeated so a nested tag cannot reassemble.
_WRAPPER_TAG = re.compile(r"<\s*/?\s*[A-Za-z][\w.:-]*\s*/?\s*>")
_MAX_WARNING_CHARS = 300

QUERY_SCAN_WARNING_TAG = "query_scan_warning"

_QUERY_SCAN_LEAD = "This query read {rows} rows in {secs} s."
_QUERY_SCAN_KILLED_LEAD = "ClickHouse stopped this query after {secs} s, having read {rows} rows."
_QUERY_SCAN_SHORT_FORM = (
    "This query read {rows} rows in {secs} s. This is likely far more than needed; check the event "
    "filter and the start date before running it again."
)
# A killed run's block rides on an error message the agent framework caps at 500 characters, so it
# carries the two findings most likely to explain the read and leaves the rest to the next run.
_COMPACT_BLOCK_MESSAGES = 2


def _collapse_warning_line(message: str, max_chars: int | None = _MAX_WARNING_CHARS) -> str:
    cleaned = re.sub(r"\s+", " ", message).strip()
    if max_chars is not None and len(cleaned) > max_chars:
        return cleaned[:max_chars] + "…"
    return cleaned


def sanitize_warning_line(message: str) -> str:
    """For a line built from project data, where no angle bracket is worth keeping."""
    return _collapse_warning_line(_ANGLE_BRACKETS.sub(" ", _UNSAFE_WARNING_CHARS.sub(" ", message)))


def sanitize_composed_warning_line(message: str, max_chars: int | None = _MAX_WARNING_CHARS) -> str:
    """For a line PostHog composes itself, where `>=` in advice has to reach the agent as written.
    `max_chars=None` keeps a long build-time line whole.
    """
    cleaned = _UNSAFE_WARNING_CHARS.sub(" ", message)
    while (without_tags := _WRAPPER_TAG.sub(" ", cleaned)) != cleaned:
        cleaned = without_tags
    return _collapse_warning_line(cleaned, max_chars)


def _warnings_of_type(response: dict[str, Any], warning_type: str) -> list[dict[str, Any]]:
    return [w for w in (response.get("warnings") or []) if w.get("type") == warning_type and w.get("message")]


def _warning_messages(
    response: dict[str, Any],
    warning_type: str,
    sanitize: Callable[[str], str] = sanitize_warning_line,
) -> list[str]:
    return [sanitize(w["message"]) for w in _warnings_of_type(response, warning_type)]


def _format_warnings(response: dict[str, Any], warning_type: str, header: str) -> str:
    """Select one kind of warning from the shared `warnings` list (by its `type` tag) and render it
    as a leading block. Empty string when there's nothing to show."""
    messages = _warning_messages(response, warning_type)
    if not messages:
        return ""
    # Trailing blank line so consecutive blocks (and the results after them) don't run together.
    return "\n".join([header, *(f"- {m}" for m in messages), "", ""])


def format_warehouse_sync_warnings(response: dict[str, Any]) -> str:
    return _format_warnings(
        response, "warehouse_sync", "[Data warehouse sync warnings — results may not reflect current source data]"
    )


def format_access_control_warnings(response: dict[str, Any]) -> str:
    # Filtering is pushed into SQL, so excluded rows never come back — without this block an agent
    # can mistake a possibly-partial result for the full set. The message is a full sentence
    # ("Results may exclude ..."), so the header is just the block label.
    return _format_warnings(response, "access_control", "[Access control]")


def format_query_scan_warnings(response: dict[str, Any], team: "Team | None" = None, *, compact: bool = False) -> str:
    """The prompt for a slow query, for the assistant and an outside MCP agent alike: the goal, the run,
    one entry per finding, and the rules. The frontend "Fix with AI" message builds the same structure.
    Nothing for `log_only`. `compact` caps the findings, for the killed-run block.
    """
    scan = response.get("query_scan")
    if not isinstance(scan, dict) or scan.get("mode") != "show":
        return ""
    rows_read = scan.get("rows_read")
    duration_ms = scan.get("duration_ms")
    if not isinstance(rows_read, int) or not isinstance(duration_ms, int):
        return ""

    numbers = {"rows": format_rows(rows_read), "secs": format_seconds(duration_ms)}
    findings = _warnings_of_type(response, "query_scan")
    if not findings:
        return _format_pending_query_scan(scan, numbers, duration_ms, team)

    if compact:
        findings = findings[:_COMPACT_BLOCK_MESSAGES]
    lead = _QUERY_SCAN_KILLED_LEAD if scan.get("killed") else _QUERY_SCAN_LEAD
    return "\n".join(
        [
            f"<{QUERY_SCAN_WARNING_TAG}>",
            ASSISTANT_GOAL,
            lead.format(**numbers),
            *_query_scan_share_lines(scan),
            *(_format_query_scan_finding(finding) for finding in findings),
            ASSISTANT_RULES,
            f"</{QUERY_SCAN_WARNING_TAG}>",
            "",
            "",
        ]
    )


def _query_scan_share_lines(scan: dict[str, Any]) -> list[str]:
    """How much of the range and of the project this run read, each omitted when the analysis could
    not measure it."""
    lines: list[str] = []
    range_share = scan.get("range_share")
    if isinstance(range_share, int | float) and not isinstance(range_share, bool):
        lines.append(f"It read about {round(range_share * 100)}% of the events in this date range.")
    project_share = scan.get("project_share")
    if isinstance(project_share, int | float) and not isinstance(project_share, bool):
        lines.append(f"It read about {round(project_share * 100)}% of the project's events.")
    return lines


def _format_query_scan_finding(finding: dict[str, Any]) -> str:
    """One finding as a bullet: kind and reason, evidence, then guidance. Each part is sanitized, since a
    finding can carry project-supplied names; the guidance is our own text and stays whole.
    """
    head = sanitize_warning_line(str(finding.get("kind") or ""))
    reason = finding.get("reason")
    if reason:
        head = f"{head} ({sanitize_warning_line(str(reason))})"
    parts = [f"{head}:"]
    evidence = finding.get("evidence")
    if evidence:
        parts.append(sanitize_composed_warning_line(str(evidence)))
    parts.append(sanitize_composed_warning_line(str(finding.get("fix") or ""), max_chars=None))
    return "- " + " ".join(parts)


def _format_pending_query_scan(
    scan: dict[str, Any], numbers: dict[str, str], duration_ms: int, team: "Team | None"
) -> str:
    """The short form, for a run whose analysis has not landed yet. Silence would read as nothing to say,
    but the person did wait.
    """
    if scan.get("status") != "pending" or duration_ms < _query_scan_floor_ms(team):
        return ""
    return f"<{QUERY_SCAN_WARNING_TAG}>{_QUERY_SCAN_SHORT_FORM.format(**numbers)}</{QUERY_SCAN_WARNING_TAG}>\n\n"


def _query_scan_floor_ms(team: "Team | None") -> int:
    if team is None:
        return DEFAULT_FLOOR_MS
    flag = get_query_scan_flag(team)
    return flag.floor_ms if flag is not None else DEFAULT_FLOOR_MS


def format_query_results_for_llm(
    query: BaseModel,
    response: dict[str, Any],
    team: "Team",
    utc_now: datetime | None = None,
) -> str | None:
    """
    Format query results into LLM-friendly text.

    This is a synchronous function that dispatches to the appropriate formatter
    based on query type. Returns None if the query type is not supported.
    """
    if utc_now is None:
        utc_now = datetime.now(UTC)

    # Saved insights store their query wrapped in a presentation envelope (`InsightVizNode` for
    # product-analytics insights, `DataVisualizationNode` / `DataTableNode` for SQL-backed ones).
    # The dispatcher below matches on the underlying query type, so unwrap the `source` first.
    if isinstance(query, InsightVizNode | DataVisualizationNode | DataTableNode):
        query = query.source

    formatted: str | None = None
    if isinstance(query, AssistantTrendsQuery | TrendsQuery):
        if is_boxplot_query(query):
            formatted = BoxPlotResultsFormatter(get_boxplot_results(response)).format()
        else:
            formatted = TrendsResultsFormatter(query, response["results"], team, utc_now).format()
    elif isinstance(query, AssistantFunnelsQuery | FunnelsQuery):
        formatted = FunnelResultsFormatter(query, response["results"], team, utc_now).format()
    elif isinstance(query, AssistantLifecycleQuery | LifecycleQuery):
        formatted = LifecycleResultsFormatter(query, response["results"]).format()
    elif isinstance(query, AssistantPathsQuery | PathsQuery):
        formatted = PathsResultsFormatter(response["results"]).format()
    elif isinstance(query, AssistantStickinessQuery | StickinessQuery):
        formatted = StickinessResultsFormatter(query, response["results"]).format()
    elif isinstance(query, AssistantRetentionQuery | RetentionQuery):
        formatted = RetentionResultsFormatter(query, response["results"]).format()
    elif isinstance(query, AssistantHogQLQuery | HogQLQuery):
        formatted = SQLResultsFormatter(query, response["results"], response["columns"]).format()

    if formatted is None:
        return None
    warning_prefix = (
        format_query_scan_warnings(response, team)
        + format_warehouse_sync_warnings(response)
        + format_access_control_warnings(response)
    )
    return warning_prefix + formatted if warning_prefix else formatted


__all__ = [
    "BoxPlotResultsFormatter",
    "FunnelResultsFormatter",
    "LifecycleResultsFormatter",
    "PathsResultsFormatter",
    "RetentionResultsFormatter",
    "SQLResultsFormatter",
    "StickinessResultsFormatter",
    "TrendsResultsFormatter",
    "TRUNCATED_MARKER",
    "NULL_MARKER",
    "format_access_control_warnings",
    "format_query_results_for_llm",
    "format_query_scan_warnings",
    "format_warehouse_sync_warnings",
    "sanitize_composed_warning_line",
    "sanitize_warning_line",
]
