from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.dataclasses import frozen
from posthog.models import Team, User
from posthog.paging import PageRequest

from ...facade.diagnostics_contracts import ErrorOrder
from ..traces.lookback import lookback_selection
from ..traces.trace_expression_queries import EVENTS_COLUMNS, error_message, event_anonymous, event_errored
from ..traces.trace_metrics import BucketSize, bucket_size_for, bucket_starts, has_no_previous_window, previous_window
from ..traces.trace_metrics_queries import last_moment, period_bucket
from ..traces.trace_selection import TraceSelection, TraceWindow
from ..traces.trace_selection_queries import counted_events, execute_selection, period_membership
from .error_groups import DEFAULT_ERROR_ORDER, ErrorCountsRow, ErrorGroupRow, ErrorView, series_of
from .group_page_queries import groups_to_sort, page_of
from .trend_queries import trend_expression
from .trends import Trend

ERRORS_PAGE_QUERY_NAME = "ai_diagnostics_errors_page"
ERROR_GROUP_QUERY_NAME = "ai_diagnostics_error_group"
ERROR_FIRST_SEEN_QUERY_NAME = "ai_diagnostics_error_first_seen"
ERRORS_NEW_COUNT_QUERY_NAME = "ai_diagnostics_errors_new_count"
ERRORS_CAPTURED_QUERY_NAME = "ai_diagnostics_errors_captured"

# Each value is ascending in the page's sort, so a descending order negates its value.
_ORDER_KEYS: dict[ErrorOrder, tuple[str, ...]] = {
    ErrorOrder.OCCURRENCES: ("negate(occurrences)",),
    # A message absent last period has no percent change. It counts as the largest rise, so these messages lead, the
    # larger count first.
    ErrorOrder.CHANGE: (
        "previous_occurrences != 0",
        "negate(if(previous_occurrences = 0, 0, (occurrences - previous_occurrences) / previous_occurrences))",
        "negate(occurrences)",
    ),
    ErrorOrder.TRACES: ("negate(traces)",),
    ErrorOrder.USERS: ("negate(users)",),
    ErrorOrder.LAST_SEEN: ("negate(toUnixTimestamp64Milli(last_seen))",),
}
_TREND_VIEWS: dict[ErrorView, Trend] = {ErrorView.INCREASING: Trend.INCREASING, ErrorView.DECREASING: Trend.DECREASING}
# The columns of one group, in the order a page row and a group read return them.
_GROUP_COLUMNS = (
    "message",
    "occurrences",
    "previous_occurrences",
    "traces",
    "users",
    "models",
    "last_seen",
    "trend",
    "series",
)


@frozen
class ErrorPageRead:
    rows: tuple[ErrorGroupRow, ...]
    count: int
    counts: ErrorCountsRow
    bucket_starts: tuple[datetime, ...]
    order: ErrorOrder


@frozen
class ErrorGroupDetailRow:
    row: ErrorGroupRow
    previous_series: tuple[int, ...]


def _message() -> ast.Expr:
    return error_message(EVENTS_COLUMNS)


def _errored_matching(match: ast.Expr) -> ast.Expr:
    return parse_expr(
        "{errored} AND isNotNull({message}) AND {match}",
        placeholders={"errored": event_errored(EVENTS_COLUMNS), "message": _message(), "match": match},
    )


def _searched(search: str | None) -> ast.Expr:
    term = (search or "").strip()
    if not term:
        return ast.Constant(value=True)
    return parse_expr(
        "positionCaseInsensitiveUTF8({message}, {term}) > 0",
        placeholders={"message": _message(), "term": ast.Constant(value=term)},
    )


def _named(messages: Sequence[str]) -> ast.Expr:
    return ast.CompareOperation(op=ast.CompareOperationOp.In, left=_message(), right=ast.Constant(value=list(messages)))


def _previous(window: TraceWindow) -> TraceWindow | None:
    return None if has_no_previous_window(window) else previous_window(window)


def _counted_rows(
    team: Team, selection: TraceSelection, previous: TraceWindow | None, match: ast.Expr
) -> ast.SelectQuery | ast.SelectSetQuery:
    current = parse_select(
        """
        SELECT
            properties.$ai_trace_id AS trace_id,
            {message} AS message,
            timestamp,
            ifNull(properties.$ai_model, '') AS model,
            person_id,
            {anonymous} AS anonymous
        FROM events
        WHERE {counted} AND {errored}
        """,
        placeholders={
            "message": _message(),
            "anonymous": event_anonymous(EVENTS_COLUMNS),
            "counted": counted_events(team, selection),
            "errored": _errored_matching(match),
        },
    )
    assert isinstance(current, ast.SelectQuery)
    if previous is None:
        return current
    # A row before the current read can only count for the previous window, which needs no model, person or anonymity.
    earlier = parse_select(
        """
        SELECT properties.$ai_trace_id AS trace_id, {message} AS message, timestamp, '' AS model, NULL AS person_id,
            false AS anonymous
        FROM events
        WHERE {counted} AND timestamp < {current_read_start} AND {errored}
        """,
        placeholders={
            "message": _message(),
            "counted": counted_events(team, replace(selection, window=previous)),
            "current_read_start": ast.Constant(value=selection.window.read_bounds().start),
            "errored": _errored_matching(match),
        },
    )
    assert isinstance(earlier, ast.SelectQuery)
    return ast.SelectSetQuery.create_from_queries([current, earlier], "UNION ALL")


def _errored_events(
    team: Team, selection: TraceSelection, previous: TraceWindow | None, match: ast.Expr
) -> ast.SelectQuery:
    # A row counts for the window whose traces hold it under the traces list's per-trace rules over all their events.
    # A trace in both windows counts only for the current one.
    query = parse_select(
        """
        SELECT
            occurrence.trace_id AS trace_id,
            traces.in_current AS in_current,
            occurrence.message AS message,
            occurrence.timestamp AS timestamp,
            occurrence.model AS model,
            occurrence.person_id AS person_id,
            occurrence.anonymous AS anonymous
        FROM {rows} AS occurrence
        INNER JOIN {traces} AS traces ON occurrence.trace_id = traces.trace_id
        WHERE (traces.in_current AND occurrence.timestamp >= {current_read_start})
            OR (NOT traces.in_current AND traces.in_previous AND occurrence.timestamp <= {previous_read_end})
        """,
        placeholders={
            "rows": _counted_rows(team, selection, previous, match),
            "traces": period_membership(team, selection, previous, holding=_errored_matching(match)),
            "current_read_start": ast.Constant(value=selection.window.read_bounds().start),
            "previous_read_end": ast.Constant(value=(previous or selection.window).read_bounds().end),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _from_lookback(team: Team, selection: TraceSelection, match: ast.Expr) -> ast.Expr:
    lookback = lookback_selection(selection)
    widened = replace(lookback, window=TraceWindow(start=lookback.window.start, end=selection.window.end))
    return parse_expr(
        "{counted} AND timestamp >= {start} AND {errored}",
        placeholders={
            "counted": counted_events(team, widened),
            "start": ast.Constant(value=lookback.window.start),
            "errored": _errored_matching(match),
        },
    )


def _seen_before(team: Team, selection: TraceSelection) -> ast.SelectQuery:
    query = parse_select(
        "SELECT {message} FROM events WHERE {from_lookback} AND timestamp < {start}",
        placeholders={
            "message": _message(),
            "from_lookback": _from_lookback(team, selection, ast.Constant(value=True)),
            "start": ast.Constant(value=selection.window.start),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _in_view(team: Team, selection: TraceSelection, view: ErrorView | None) -> ast.Expr:
    if view is None:
        return ast.Constant(value=True)
    if view == ErrorView.NEW:
        return parse_expr("message NOT IN {seen}", placeholders={"seen": _seen_before(team, selection)})
    return parse_expr("trend = {trend}", placeholders={"trend": ast.Constant(value=_TREND_VIEWS[view].value)})


def _bucket(size: BucketSize, window: TraceWindow, previous: TraceWindow | None) -> ast.Expr:
    previous = previous or window
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


def _groups(
    team: Team, selection: TraceSelection, size: BucketSize, match: ast.Expr, in_view: ast.Expr
) -> ast.SelectQuery:
    """One row per message with a flagged event in the range, over the events `match` keeps, with `in_view`."""
    previous = _previous(selection.window)
    # topK orders equal counts by merge order, which changes between runs, so models rank by count and then name.
    query = parse_select(
        """
        SELECT
            message,
            countIf(in_current) AS occurrences,
            countIf(NOT in_current) AS previous_occurrences,
            uniqIf(trace_id, in_current) AS traces,
            uniqIf(person_id, in_current AND NOT anonymous) AS users,
            sumMapIf([model], [1], in_current AND model != '') AS model_counts,
            arrayMap(x -> x.1, arraySlice(arraySort(x -> (-x.2, x.1), arrayZip(model_counts.1, model_counts.2)), 1, 3)) AS models,
            maxIf(timestamp, in_current) AS last_seen,
            {trend} AS trend,
            sumMapIf([bucket], [1], in_current) AS series,
            sumMapIf([bucket], [1], NOT in_current) AS previous_series,
            {in_view} AS in_view
        FROM (SELECT *, {bucket} AS bucket FROM {events})
        GROUP BY message
        HAVING occurrences > 0
        """,
        placeholders={
            "trend": trend_expression(
                ast.Field(chain=["occurrences"]),
                ast.Field(chain=["previous_occurrences"]) if previous is not None else None,
            ),
            "in_view": in_view,
            "bucket": _bucket(size, selection.window, previous),
            "events": _errored_events(team, selection, previous, match),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _fields(names: Sequence[str]) -> list[ast.Expr]:
    return [ast.Field(chain=[name]) for name in names]


def _page_query(
    team: Team,
    selection: TraceSelection,
    size: BucketSize,
    *,
    search: str | None,
    view: ErrorView | None,
    order: ErrorOrder,
    page: PageRequest,
) -> ast.SelectQuery:
    sort_key = ast.Tuple(exprs=[*(parse_expr(key) for key in _ORDER_KEYS[order]), ast.Field(chain=["message"])])
    sorted_groups = parse_expr(
        "groupArraySortedIf({take})(tuple({sort_key}, {row}), in_view)",
        placeholders={
            "take": ast.Constant(value=groups_to_sort(page)),
            "sort_key": sort_key,
            "row": ast.Tuple(exprs=_fields(_GROUP_COLUMNS)),
        },
    )
    query = parse_select(
        """
        SELECT
            count() AS total,
            countIf(trend = {increasing}) AS increasing,
            countIf(trend = {decreasing}) AS decreasing,
            max(occurrences) AS max_occurrences,
            countIf(in_view) AS matching,
            {page} AS page
        FROM {groups}
        """,
        placeholders={
            "increasing": ast.Constant(value=Trend.INCREASING.value),
            "decreasing": ast.Constant(value=Trend.DECREASING.value),
            "page": page_of(sorted_groups, page),
            "groups": _groups(team, selection, size, _searched(search), _in_view(team, selection, view)),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _row(values: Sequence[Any], starts: Sequence[datetime], *, has_previous: bool) -> ErrorGroupRow:
    message, occurrences, previous_occurrences, traces, users, models, last_seen, trend, series = values
    return ErrorGroupRow(
        message=message,
        occurrences=occurrences,
        previous_occurrences=previous_occurrences if has_previous else None,
        traces=traces,
        users=users,
        models=tuple(models),
        last_seen=last_seen.astimezone(UTC),
        trend=Trend(trend),
        series=series_of(dict(zip(*series)), starts),
    )


def load_error_page(
    team: Team,
    user: User | None,
    selection: TraceSelection,
    *,
    search: str | None,
    view: ErrorView | None,
    order: ErrorOrder | None,
    page: PageRequest,
) -> ErrorPageRead:
    """A page of the selection's error messages, how many are in `view`, and the trend counts, sorted by `order` or
    by `DEFAULT_ERROR_ORDER` without one. `search` narrows the messages and the counts, and `view` only the page. The
    window must be in the project's zone."""
    applied = order or DEFAULT_ERROR_ORDER
    size = bucket_size_for(selection.window)
    starts = bucket_starts(selection.window, size)
    has_previous = not has_no_previous_window(selection.window)
    query = _page_query(team, selection, size, search=search, view=view, order=applied, page=page)
    [[total, increasing, decreasing, max_occurrences, matching, rows]] = execute_selection(
        team, user, selection, query, ERRORS_PAGE_QUERY_NAME
    )
    return ErrorPageRead(
        rows=tuple(_row(values, starts, has_previous=has_previous) for _, values in rows),
        count=matching,
        counts=ErrorCountsRow(
            total=total, increasing=increasing, decreasing=decreasing, max_occurrences=max_occurrences
        ),
        bucket_starts=tuple(starts),
        order=applied,
    )


def load_error_group(
    team: Team, user: User | None, selection: TraceSelection, message: str
) -> ErrorGroupDetailRow | None:
    """The message's group over the selection, with its series over the previous window's buckets, or None when the
    message has no flagged event in the range."""
    window = selection.window
    size = bucket_size_for(window)
    query = parse_select(
        "SELECT {columns}, previous_series FROM {groups} LIMIT 1",
        placeholders={
            "columns": ast.Tuple(exprs=_fields(_GROUP_COLUMNS)),
            "groups": _groups(team, selection, size, _named([message]), ast.Constant(value=True)),
        },
    )
    results = execute_selection(team, user, selection, query, ERROR_GROUP_QUERY_NAME)
    if not results:
        return None
    [[values, previous_series]] = results
    previous = _previous(window)
    return ErrorGroupDetailRow(
        row=_row(values, bucket_starts(window, size), has_previous=previous is not None),
        previous_series=series_of(dict(zip(*previous_series)), bucket_starts(previous, size))
        if previous is not None
        else (),
    )


def count_new_errors(team: Team, user: User | None, selection: TraceSelection, *, search: str | None) -> int:
    query = parse_select(
        "SELECT count() FROM (SELECT DISTINCT message FROM {events} WHERE in_current) WHERE message NOT IN {seen}",
        placeholders={
            "events": _errored_events(team, selection, None, _searched(search)),
            "seen": _seen_before(team, selection),
        },
    )
    [[count]] = execute_selection(team, user, selection, query, ERRORS_NEW_COUNT_QUERY_NAME, list_time_limit=False)
    return count


def load_error_first_seen(
    team: Team, user: User | None, selection: TraceSelection, messages: Sequence[str]
) -> dict[str, datetime]:
    """Each message's earliest flagged event from the lookback start to the range end, if it has one."""
    if not messages:
        return {}
    query = parse_select(
        "SELECT {message} AS message, min(timestamp) FROM events WHERE {from_lookback} GROUP BY message",
        placeholders={"message": _message(), "from_lookback": _from_lookback(team, selection, _named(messages))},
    )
    results = execute_selection(
        team, user, lookback_selection(selection), query, ERROR_FIRST_SEEN_QUERY_NAME, list_time_limit=False
    )
    return {message: earliest.astimezone(UTC) for message, earliest in results}


def has_any_error(team: Team, user: User | None, selection: TraceSelection) -> bool:
    """Whether any flagged event with a message was captured from the lookback start to the range end."""
    query = parse_select(
        "SELECT 1 FROM events WHERE {from_lookback} LIMIT 1",
        placeholders={"from_lookback": _from_lookback(team, selection, ast.Constant(value=True))},
    )
    return bool(execute_selection(team, user, lookback_selection(selection), query, ERRORS_CAPTURED_QUERY_NAME))
