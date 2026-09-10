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

from posthog.query_scan.findings import format_rows, format_seconds
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


# A warning message can carry names the project's own event data supplies, and anyone capturing
# events controls those. The message goes verbatim into agent context, so strip control characters
# and newlines, and cap length. This can't stop plain-text influence (no escaping can), but it keeps
# the names contained as data inside the labeled block.
_UNSAFE_WARNING_CHARS = re.compile(r"[\x00-\x1f\x7f]")
# Dropping every angle bracket stops a crafted name (for example one containing
# `</taxonomy_warnings>`) from closing the wrapper early and breaking out of the delimited block.
_ANGLE_BRACKETS = re.compile(r"[<>]")
# A line PostHog composes itself carries no project data but does carry comparison operators, so
# take out only the shapes that could close a wrapper. Repeat until nothing changes, so a nested
# `<</tag>/tag>` cannot reassemble into a tag after one pass.
_WRAPPER_TAG = re.compile(r"<\s*/?\s*[A-Za-z][\w.:-]*\s*/?\s*>")
_MAX_WARNING_CHARS = 300

QUERY_SCAN_WARNING_TAG = "query_scan_warning"

_QUERY_SCAN_LEAD = "This query read {rows} rows in {secs} s, far more than it needs."
_QUERY_SCAN_KILLED_LEAD = "ClickHouse stopped this query after {secs} s, having read {rows} rows."
_QUERY_SCAN_INSTRUCTION = (
    "First run bounded exploratory queries to see what the data looks like, each with a recent "
    "`timestamp` bound and a `LIMIT`, for example `SELECT event, count() FROM events WHERE the other "
    "conditions AND timestamp >= now() - interval 7 day GROUP BY event ORDER BY count() DESC LIMIT 20`. "
    "Then tell the user which filter is missing, propose a rewrite that keeps the question the same, "
    "and ask them to confirm before running it again. Do not narrow the query without saying so. "
    "Never invent event names or dates: if you cannot tell which events the question is about, say so "
    "and leave a `-- fill in the events this question is about` comment where the filter goes."
)
_QUERY_SCAN_SHORT_FORM = (
    "This query read {rows} rows in {secs} s. This is likely far more than needed; check the event "
    "filter and the start date before running it again."
)
# A killed run's block rides on an error message the agent framework caps at 500 characters, so it
# carries the two findings most likely to explain the read and leaves the rest to the next run.
_COMPACT_BLOCK_MESSAGES = 2


def _collapse_warning_line(message: str) -> str:
    cleaned = re.sub(r"\s+", " ", message).strip()
    return cleaned[:_MAX_WARNING_CHARS] + "…" if len(cleaned) > _MAX_WARNING_CHARS else cleaned


def sanitize_warning_line(message: str) -> str:
    """For a line built from project data, where no angle bracket is worth keeping."""
    return _collapse_warning_line(_ANGLE_BRACKETS.sub(" ", _UNSAFE_WARNING_CHARS.sub(" ", message)))


def sanitize_composed_warning_line(message: str) -> str:
    """For a line PostHog composes itself, where `timestamp >= now() - interval 30 day` has to reach
    the agent as written. Stripping the bracket would turn that advice into an equality test, so the
    agent would propose a predicate matching almost nothing."""
    cleaned = _UNSAFE_WARNING_CHARS.sub(" ", message)
    while (without_tags := _WRAPPER_TAG.sub(" ", cleaned)) != cleaned:
        cleaned = without_tags
    return _collapse_warning_line(cleaned)


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
    """Tell the agent that this run read far more data than the question needs, and what to change.

    The block is the only channel to an outside MCP agent, so the standing instruction is inside it
    rather than only in the in-app assistant's prompt. `log_only` teams get nothing: the flag mode
    says what a client may show.

    `compact` caps the findings, for the killed-run block that has to share a capped error message.
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

    messages = [sanitize_composed_warning_line(finding["message"]) for finding in findings]
    if compact:
        messages = messages[:_COMPACT_BLOCK_MESSAGES]
    lead = _QUERY_SCAN_KILLED_LEAD if scan.get("killed") else _QUERY_SCAN_LEAD
    return "\n".join(
        [
            f"<{QUERY_SCAN_WARNING_TAG}>",
            lead.format(**numbers),
            *(f"- {message}" for message in messages),
            _QUERY_SCAN_INSTRUCTION,
            f"</{QUERY_SCAN_WARNING_TAG}>",
            "",
            "",
        ]
    )


def _format_pending_query_scan(
    scan: dict[str, Any], numbers: dict[str, str], duration_ms: int, team: "Team | None"
) -> str:
    """The short form, for a run whose analysis has not landed yet.

    A finished analysis that found nothing is silence: the query was slow for a reason we have no
    advice about. A pending one still means the person waited, which is worth saying on its own.
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
