from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.paging import PageRequest

from ...facade.diagnostics_contracts import ToolOrder
from ..traces.lookback import lookback_selection
from ..traces.trace_expression_queries import EVENTS_COLUMNS, tool_names
from ..traces.trace_metrics import BucketSize, bucket_size_for, bucket_starts, has_no_previous_window
from ..traces.trace_selection import TraceSelection, TraceWindow
from ..traces.trace_selection_queries import counted_events, execute_selection
from .group_page_queries import (
    bucket_seconds,
    change_order,
    contains_search,
    fields,
    groups_to_sort,
    previous_period,
    rows_in_periods,
    since_lookback,
)
from .tool_groups import DEFAULT_TOOL_ORDER, ToolCountsRow, ToolGroupRow, ToolView
from .trend_queries import failing_expression, failure_rate_expression
from .trends import series_of

TOOLS_PAGE_QUERY_NAME = "ai_diagnostics_tools_page"
TOOL_GROUP_QUERY_NAME = "ai_diagnostics_tool_group"
TOOLS_CAPTURED_QUERY_NAME = "ai_diagnostics_tools_captured"
TOOL_TRACES_QUERY_NAME = "ai_diagnostics_tool_traces"

# Each value is ascending in the page's sort, so a descending order negates its value.
_ORDER_KEYS: dict[ToolOrder, tuple[str, ...]] = {
    ToolOrder.CALLS: ("negate(calls)",),
    ToolOrder.CHANGE: change_order("calls", "previous_calls"),
    ToolOrder.TRACES: ("negate(traces)",),
    # A tool with no captured result has no failure rate, so it follows every tool that has one.
    ToolOrder.FAILURE_RATE: ("isNull(failure_rate)", "negate(ifNull(failure_rate, 0))", "negate(calls)"),
    ToolOrder.LAST_SEEN: ("negate(toUnixTimestamp64Milli(last_seen))",),
}
_VIEWS: dict[ToolView, str] = {ToolView.FAILING: "is_failing"}
# The columns of one group, in the order a page row and a group read return them.
_GROUP_COLUMNS = (
    "name",
    "calls",
    "previous_calls",
    "traces",
    "results",
    "failures",
    "failure_rate",
    "only_tool_calls",
    "last_seen",
    "is_failing",
    "series",
)


class _Part(StrEnum):
    CALL = "call"
    RESULT = "result"
    FAILURE = "failure"


@frozen
class ToolPageRead:
    rows: tuple[ToolGroupRow, ...]
    count: int
    counts: ToolCountsRow
    bucket_starts: tuple[datetime, ...]
    order: ToolOrder


@frozen
class ToolGroupDetailRow:
    row: ToolGroupRow
    previous_series: tuple[int, ...]


def _names(property_name: str) -> ast.Expr:
    return tool_names(EVENTS_COLUMNS, property_name)


def _parts(names: str, part: _Part, *, single: ast.Expr) -> ast.Expr:
    return parse_expr(
        "arrayMap(name -> tuple(name, {part}, {single}), {names})",
        placeholders={"names": ast.Field(chain=[names]), "part": ast.Constant(value=part.value), "single": single},
    )


def _carries_tools() -> ast.Expr:
    return parse_expr(
        "event = '$ai_generation' AND (notEmpty({called}) OR notEmpty({results}) OR notEmpty({failures}))",
        placeholders={
            "called": _names("$ai_tools_called"),
            "results": _names("$ai_tool_results"),
            "failures": _names("$ai_tool_errors"),
        },
    )


def _tool_rows(team: Team, selection: TraceSelection, previous: TraceWindow | None) -> ast.SelectQuery:
    """The counted generations that call a tool or receive a tool's result, over both windows."""
    span = selection.window if previous is None else TraceWindow(start=previous.start, end=selection.window.end)
    query = parse_select(
        """
        SELECT properties.$ai_trace_id AS trace_id, timestamp, {called} AS called, {results} AS results,
            {failures} AS failures
        FROM events
        WHERE {counted} AND {carries_tools}
        """,
        placeholders={
            "called": _names("$ai_tools_called"),
            "results": _names("$ai_tool_results"),
            "failures": _names("$ai_tool_errors"),
            "counted": counted_events(team, replace(selection, window=span)),
            "carries_tools": _carries_tools(),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _tool_events(
    team: Team, selection: TraceSelection, previous: TraceWindow | None, match: ast.Expr
) -> ast.SelectQuery:
    """One row per name a generation calls, and in the range also per result and failed result it receives, with
    `single` marking a call from a generation that calls one tool."""
    calls = _parts("called", _Part.CALL, single=parse_expr("length(called) = 1"))
    query = parse_select(
        """
        SELECT
            trace_id,
            in_current,
            tupleElement(tool_part, 1) AS name,
            tupleElement(tool_part, 2) AS part,
            timestamp,
            tupleElement(tool_part, 3) AS single
        FROM (
            SELECT trace_id, in_current, timestamp,
                arrayJoin(if(in_current, arrayConcat({calls}, {results}, {failures}), {calls})) AS tool_part
            FROM {generations}
        )
        WHERE {match}
        """,
        placeholders={
            "calls": calls,
            "results": _parts("results", _Part.RESULT, single=ast.Constant(value=0)),
            "failures": _parts("failures", _Part.FAILURE, single=ast.Constant(value=0)),
            "generations": rows_in_periods(
                team,
                selection,
                previous,
                _tool_rows(team, selection, previous),
                ("timestamp", "called", "results", "failures"),
                holding=_carries_tools(),
            ),
            "match": match,
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _traces() -> ast.Expr:
    """A tool's Traces: the traces of the range that call it."""
    return parse_expr(
        "uniqIf(trace_id, part = {call} AND in_current)", placeholders={"call": ast.Constant(value=_Part.CALL.value)}
    )


def _groups(team: Team, selection: TraceSelection, size: BucketSize, match: ast.Expr) -> ast.SelectQuery:
    """One row per tool a generation in the range calls, over the names `match` keeps."""
    query = parse_select(
        """
        SELECT
            name,
            countIf(part = {call} AND in_current) AS calls,
            countIf(part = {call} AND NOT in_current) AS previous_calls,
            {traces} AS traces,
            countIf(part = {result} AND in_current) AS results,
            countIf(part = {failure} AND in_current) AS failures,
            {failure_rate} AS failure_rate,
            countIf(part = {call} AND in_current AND single) AS only_tool_calls,
            maxIf(timestamp, part = {call} AND in_current) AS last_seen,
            {failing} AS is_failing,
            sumMapIf([bucket], [1], part = {call} AND in_current) AS series,
            sumMapIf([bucket], [1], part = {call} AND NOT in_current) AS previous_series
        FROM (SELECT *, {bucket} AS bucket FROM {events})
        GROUP BY name
        HAVING calls > 0
        """,
        placeholders={
            "call": ast.Constant(value=_Part.CALL.value),
            "traces": _traces(),
            "result": ast.Constant(value=_Part.RESULT.value),
            "failure": ast.Constant(value=_Part.FAILURE.value),
            "failure_rate": failure_rate_expression(ast.Field(chain=["results"]), ast.Field(chain=["failures"])),
            "failing": failing_expression(ast.Field(chain=["results"]), ast.Field(chain=["failure_rate"])),
            "bucket": bucket_seconds(size, selection.window),
            "events": _tool_events(team, selection, previous_period(selection.window), match),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _named(name: str) -> ast.Expr:
    return parse_expr("name = {name}", placeholders={"name": ast.Constant(value=name)})


def _page_query(
    team: Team,
    selection: TraceSelection,
    size: BucketSize,
    *,
    search: str | None,
    view: ToolView | None,
    order: ToolOrder,
    page: PageRequest,
) -> ast.SelectQuery:
    sort_key = ast.Tuple(exprs=[*(parse_expr(key) for key in _ORDER_KEYS[order]), ast.Field(chain=["name"])])
    query = parse_select(
        """
        SELECT
            count() AS total,
            countIf(is_failing) AS failing,
            max(calls) AS max_calls,
            countIf({in_view}) AS matching,
            groupArraySortedIf({take})(tuple({sort_key}, {row}), {in_view}) AS page
        FROM {groups}
        """,
        placeholders={
            "in_view": parse_expr(_VIEWS[view]) if view is not None else ast.Constant(value=True),
            "take": ast.Constant(value=groups_to_sort(page)),
            "sort_key": sort_key,
            "row": ast.Tuple(exprs=fields(_GROUP_COLUMNS)),
            "groups": _groups(team, selection, size, contains_search(ast.Field(chain=["name"]), search)),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _row(values: Sequence[Any], starts: Sequence[datetime], *, has_previous: bool) -> ToolGroupRow:
    (
        name,
        calls,
        previous_calls,
        traces,
        results,
        failures,
        failure_rate,
        only_tool_calls,
        last_seen,
        is_failing,
        series,
    ) = values
    return ToolGroupRow(
        name=name,
        calls=calls,
        previous_calls=previous_calls if has_previous else None,
        traces=traces,
        results=results,
        failures=failures,
        failure_rate=failure_rate,
        only_tool_calls=only_tool_calls,
        last_seen=last_seen.astimezone(UTC),
        is_failing=bool(is_failing),
        series=series_of(dict(zip(*series)), starts),
    )


def load_tool_page(
    team: Team,
    user: User | None,
    selection: TraceSelection,
    *,
    search: str | None,
    view: ToolView | None,
    order: ToolOrder | None,
    page: PageRequest,
) -> ToolPageRead:
    """A page of the tools the selection's generations call, sorted by `order` or by `DEFAULT_TOOL_ORDER` without one,
    the number of tools in `view`, and the counts of every view with the most calls of any tool. `search` narrows the
    tools and the counts, and `view` only the page. The selection's window must be in the project's zone, where
    ClickHouse floors the buckets."""
    applied = order or DEFAULT_TOOL_ORDER
    size = bucket_size_for(selection.window)
    starts = bucket_starts(selection.window, size)
    has_previous = not has_no_previous_window(selection.window)
    query = _page_query(team, selection, size, search=search, view=view, order=applied, page=page)
    [[total, failing, max_calls, matching, rows]] = execute_selection(
        team, user, selection, query, TOOLS_PAGE_QUERY_NAME
    )
    return ToolPageRead(
        rows=tuple(_row(values, starts, has_previous=has_previous) for _, values in rows[page.offset :]),
        count=matching,
        counts=ToolCountsRow(total=total, failing=failing, max_calls=max_calls),
        bucket_starts=tuple(starts),
        order=applied,
    )


def load_tool_group(team: Team, user: User | None, selection: TraceSelection, name: str) -> ToolGroupDetailRow | None:
    """The tool's group over the selection, with its series over the previous window's buckets, or None when no
    generation in the range calls the tool."""
    window = selection.window
    size = bucket_size_for(window)
    query = parse_select(
        "SELECT {row}, previous_series FROM {groups} LIMIT 1",
        placeholders={
            "row": ast.Tuple(exprs=fields(_GROUP_COLUMNS)),
            "groups": _groups(team, selection, size, _named(name)),
        },
    )
    results = execute_selection(team, user, selection, query, TOOL_GROUP_QUERY_NAME)
    if not results:
        return None
    [[values, previous_series]] = results
    previous = previous_period(window)
    return ToolGroupDetailRow(
        row=_row(values, bucket_starts(window, size), has_previous=previous is not None),
        previous_series=series_of(dict(zip(*previous_series)), bucket_starts(previous, size))
        if previous is not None
        else (),
    )


def load_tool_traces(team: Team, user: User | None, selection: TraceSelection, names: Sequence[str]) -> dict[str, int]:
    """How many of the range's traces call each of `names`. A name no generation in the range calls has no entry."""
    if not names:
        return {}
    named = ast.CompareOperation(
        op=ast.CompareOperationOp.In, left=ast.Field(chain=["name"]), right=ast.Constant(value=list(names))
    )
    query = parse_select(
        "SELECT name, {traces} FROM {events} GROUP BY name",
        placeholders={
            "traces": _traces(),
            "events": _tool_events(team, selection, None, named),
        },
    )
    results = execute_selection(team, user, selection, query, TOOL_TRACES_QUERY_NAME, list_time_limit=False)
    return {name: traces for name, traces in results if traces}


def has_any_tool_call(team: Team, user: User | None, selection: TraceSelection) -> bool:
    """Whether any generation called a tool from the lookback start to the range end, under the lookback's rules."""
    query = parse_select(
        "SELECT 1 FROM events WHERE {since_lookback} AND event = '$ai_generation' AND notEmpty({called}) LIMIT 1",
        placeholders={"since_lookback": since_lookback(team, selection), "called": _names("$ai_tools_called")},
    )
    return bool(execute_selection(team, user, lookback_selection(selection), query, TOOLS_CAPTURED_QUERY_NAME))
