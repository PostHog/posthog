from collections.abc import Sequence
from dataclasses import replace
from typing import Final

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.models import Team
from posthog.paging import PageRequest

from ..traces.lookback import lookback_selection
from ..traces.trace_metrics import BucketSize, has_no_previous_window, previous_window
from ..traces.trace_metrics_queries import last_moment, period_bucket
from ..traces.trace_selection import TraceSelection, TraceWindow
from ..traces.trace_selection_queries import counted_events, period_membership

# ClickHouse refuses a groupArraySorted size above this, so a page read sorts at most this many groups. An offset past
# it reads an empty page, and the counts still cover every group.
MAX_SORTED_GROUPS: Final = 16_777_215


def groups_to_sort(page: PageRequest) -> int:
    """How many of the first groups a page read sorts, from which it keeps the page's own."""
    return min(page.offset + page.limit, MAX_SORTED_GROUPS)


def change_order(current: str, previous: str) -> tuple[str, ...]:
    """The sort keys of the change order, each ascending in the page's sort, over two group columns."""
    # A group absent last period has no percent change. It counts as the largest rise, so these groups lead, the larger
    # count first.
    return (
        f"{previous} != 0",
        f"negate(if({previous} = 0, 0, ({current} - {previous}) / {previous}))",
        f"negate({current})",
    )


def contains_search(value: ast.Expr, search: str | None) -> ast.Expr:
    term = (search or "").strip()
    if not term:
        return ast.Constant(value=True)
    return parse_expr(
        "positionCaseInsensitiveUTF8({value}, {term}) > 0",
        placeholders={"value": value, "term": ast.Constant(value=term)},
    )


def fields(names: Sequence[str]) -> list[ast.Expr]:
    return [ast.Field(chain=[name]) for name in names]


def previous_period(window: TraceWindow) -> TraceWindow | None:
    return None if has_no_previous_window(window) else previous_window(window)


def rows_in_periods(
    team: Team,
    selection: TraceSelection,
    previous: TraceWindow | None,
    rows: ast.SelectQuery | ast.SelectSetQuery,
    columns: Sequence[str],
    *,
    holding: ast.Expr,
) -> ast.SelectQuery:
    """The `rows` that count for the range or for `previous`, with their `trace_id`, `in_current` and `columns`,
    read only over the traces with an event `holding` matches."""
    # A row counts for the window whose traces hold it under the traces list's per-trace rules over all their events.
    # A trace in both windows counts only for the current one.
    query = parse_select(
        """
        SELECT counted.trace_id AS trace_id, traces.in_current AS in_current
        FROM {rows} AS counted
        INNER JOIN {traces} AS traces ON counted.trace_id = traces.trace_id
        WHERE (traces.in_current AND counted.timestamp >= {current_read_start})
            OR (NOT traces.in_current AND traces.in_previous AND counted.timestamp <= {previous_read_end})
        """,
        placeholders={
            "rows": rows,
            "traces": period_membership(team, selection, previous, holding=holding),
            "current_read_start": ast.Constant(value=selection.window.read_bounds().start),
            "previous_read_end": ast.Constant(value=(previous or selection.window).read_bounds().end),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    query.select.extend(ast.Alias(alias=column, expr=ast.Field(chain=["counted", column])) for column in columns)
    return query


def bucket_seconds(size: BucketSize, window: TraceWindow) -> ast.Expr:
    """The Unix seconds of the bucket a row's `timestamp` falls in, within the period its `in_current` names."""
    previous = window if has_no_previous_window(window) else previous_window(window)
    period_start = parse_expr(
        "if(in_current, {current}, {previous})",
        placeholders={"current": ast.Constant(value=window.start), "previous": ast.Constant(value=previous.start)},
    )
    period_last_moment = parse_expr(
        "if(in_current, {current}, {previous})",
        placeholders={"current": last_moment(window), "previous": last_moment(previous)},
    )
    bucket = period_bucket(size, ast.Field(chain=["timestamp"]), period_start, period_last_moment)
    return ast.Call(name="toUnixTimestamp", args=[bucket])


def since_lookback(team: Team, selection: TraceSelection) -> ast.Expr:
    """The events from the lookback start to the range end with its read buffer, under the lookback's rules, which
    ignore the selection's property filters and scopes and the traces the events belong to."""
    lookback = lookback_selection(selection)
    widened = replace(lookback, window=TraceWindow(start=lookback.window.start, end=selection.window.end))
    return parse_expr(
        "{counted} AND timestamp >= {start}",
        placeholders={"counted": counted_events(team, widened), "start": ast.Constant(value=lookback.window.start)},
    )


def page_of(sorted_groups: ast.Expr, page: PageRequest) -> ast.Expr:
    """The page's own groups of the groups a page read sorts, so that a deep page returns no more rows than a first
    one."""
    return ast.Call(
        name="arraySlice",
        args=[sorted_groups, ast.Constant(value=page.offset + 1), ast.Constant(value=page.limit)],
    )
