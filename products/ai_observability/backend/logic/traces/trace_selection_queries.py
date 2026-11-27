from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from posthog.schema import AnyPropertyFilterDiscriminated, EventPropertyFilter

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.errors import NotImplementedError as HogQLNotImplementedError
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Product, tag_queries, tags_context
from posthog.dataclasses import frozen
from posthog.hogql_queries.ai.ai_column_rewriter import EVENTS_FALLBACK_PROPERTY_TYPE_OVERRIDES
from posthog.hogql_queries.ai.utils import filled_property_filters
from posthog.models import Team, User
from posthog.models.group_type_mapping import get_group_types_for_project

from .trace_expression_queries import (
    EVENTS_COLUMNS,
    TRACE_EVENT_NAMES,
    error_message,
    event_errored,
    grouped,
    names_session,
    not_impersonated,
    tool_names,
    trace_errored,
)
from .trace_paging import AroundTakes, RowsAfter, RowsAround, RowsBefore
from .trace_queries import FEEDBACK_EVENT_NAMES
from .trace_selection import (
    QUERY_SCOPED_FILTERS,
    InvalidTraceSelectionError,
    QuickFilter,
    TracePosition,
    TraceSelection,
    TraceWindow,
    filters_test_accounts,
)

SELECTION_QUERY_NAME = "ai_traces_selection"
SESSION_SELECTION_QUERY_NAME = "ai_session_traces_selection"
TRACE_COUNT_QUERY_NAME = "ai_traces_count"
BEFORE_QUERY_SUFFIX = "_before"
AROUND_QUERY_SUFFIX = "_around"
# Recency-ordered cap on the traces a search matches: older matches drop once a search hits more than this.
SEARCH_CANDIDATE_TRACE_LIMIT = 100_000
AI_TRACE_EVENTS = (*TRACE_EVENT_NAMES, *FEEDBACK_EVENT_NAMES)
_SELECTION_QUERY_SECONDS = 30
_QUICK_FILTER_FACTS: dict[QuickFilter, str] = {"errors": "has_error", "feedback": "has_feedback"}
_QUERY_SCOPED_FILTER_TYPES = frozenset(cls.model_fields["type"].default for cls in QUERY_SCOPED_FILTERS)
_VIRTUAL_PROPERTY_PREFIX = "$virt_"


@frozen
class SelectionCounts:
    total: int
    errors: int
    feedback: int


@frozen
class SelectionRead:
    rows: RowsAfter
    counts: SelectionCounts | None


def _all(exprs: Sequence[ast.Expr]) -> ast.Expr:
    return ast.And(exprs=list(exprs)) if exprs else ast.Constant(value=True)


def _escape_like_pattern(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _named_in(property_name: str, name: str) -> ast.Expr:
    return parse_expr(
        "event = '$ai_generation' AND has({names}, {name})",
        placeholders={"names": tool_names(EVENTS_COLUMNS, property_name), "name": ast.Constant(value=name)},
    )


def _trace_scope_events(selection: TraceSelection) -> list[ast.Expr]:
    events: list[ast.Expr] = []
    if selection.person_id is not None:
        events.append(
            parse_expr("person_id = {person_id}", placeholders={"person_id": ast.Constant(value=selection.person_id)})
        )
    if selection.error is not None:
        events.append(
            parse_expr(
                "{errored} AND {message} = {error}",
                placeholders={
                    "errored": event_errored(EVENTS_COLUMNS),
                    "message": error_message(EVENTS_COLUMNS),
                    "error": ast.Constant(value=selection.error),
                },
            )
        )
    if selection.tool is not None:
        events.append(_named_in("$ai_tools_called", selection.tool))
    if selection.failed_tool is not None:
        events.append(_named_in("$ai_tool_errors", selection.failed_tool))
    return events


def _trace_scopes(selection: TraceSelection) -> list[ast.Expr]:
    # The scopes test the grouped events and not each event read, because an event filter would drop the trace's other
    # events and so change its totals and its place in the list.
    return [
        parse_expr("countIf({event}) > 0", placeholders={"event": event}) for event in _trace_scope_events(selection)
    ]


def _group_scope(selection: TraceSelection) -> list[ast.Expr]:
    if selection.group is None:
        return []
    return [
        ast.CompareOperation(
            op=ast.CompareOperationOp.Eq,
            left=ast.Field(chain=[f"$group_{selection.group.type_index}"]),
            right=ast.Constant(value=selection.group.key),
        )
    ]


def _events_in(names: Sequence[str]) -> ast.Tuple:
    return ast.Tuple(exprs=[ast.Constant(value=name) for name in names])


def _filter_expr(team: Team, prop: AnyPropertyFilterDiscriminated) -> ast.Expr:
    try:
        return property_to_expr(prop, team)
    except HogQLNotImplementedError as error:
        raise InvalidTraceSelectionError(
            "One of the property filters can't be applied to traces. Change its operator or remove it."
        ) from error


def _property_filters(team: Team, selection: TraceSelection) -> list[ast.Expr]:
    return [_filter_expr(team, prop) for prop in filled_property_filters(selection.properties)]


def _search_filter(team: Team, selection: TraceSelection, search: str) -> ast.Expr:
    # Content lives only in ai_events. Event property filters narrow the candidates too, so the cap keeps traces that
    # can still select; other filters and the person scope need joins and person overrides only the events read has.
    bounds = selection.window.read_bounds()
    event_filters = [
        _filter_expr(team, prop)
        for prop in filled_property_filters(selection.properties)
        if isinstance(prop, EventPropertyFilter)
    ]
    candidates = parse_select(
        """
        SELECT trace_id
        FROM posthog.ai_events
        WHERE timestamp >= {start} AND timestamp <= {end}
        GROUP BY trace_id
        HAVING countIf(
            event IN ('$ai_generation', '$ai_embedding')
            AND (input ILIKE {pattern} OR output ILIKE {pattern} OR output_choices ILIKE {pattern})
        ) > 0 AND countIf({event_filters}) > 0
        ORDER BY max(timestamp) DESC
        LIMIT {candidate_limit}
        """,
        placeholders={
            "start": ast.Constant(value=bounds.start),
            "end": ast.Constant(value=bounds.end),
            "pattern": ast.Constant(value=f"%{_escape_like_pattern(search)}%"),
            "event_filters": _all(event_filters),
            "candidate_limit": ast.Constant(value=SEARCH_CANDIDATE_TRACE_LIMIT),
        },
    )
    return ast.CompareOperation(
        op=ast.CompareOperationOp.GlobalIn,
        left=ast.Field(chain=["properties", "$ai_trace_id"]),
        right=candidates,
    )


def _event_condition(team: Team, selection: TraceSelection) -> ast.Expr:
    bounds = selection.window.read_bounds()
    exprs: list[ast.Expr] = [
        parse_expr(
            """
            event IN {events}
            AND timestamp >= {start} AND timestamp <= {end}
            AND isNotNull(properties.$ai_trace_id) AND properties.$ai_trace_id != ''
            """,
            placeholders={
                "events": _events_in(AI_TRACE_EVENTS),
                "start": ast.Constant(value=bounds.start),
                "end": ast.Constant(value=bounds.end),
            },
        )
    ]
    if filters_test_accounts(team, selection):
        exprs.extend(_filter_expr(team, prop) for prop in team.test_account_filters or [])
    if not selection.include_support_traces:
        exprs.append(not_impersonated())
    exprs.extend(_group_scope(selection))
    if selection.session_id is not None:
        exprs.append(names_session(EVENTS_COLUMNS, [selection.session_id]))
    search = (selection.search or "").strip()
    if search:
        exprs.append(_search_filter(team, selection, search))
    return _all(exprs)


def counted_events(team: Team, selection: TraceSelection) -> ast.Expr:
    """The events of the selection's window, with its read buffer, that a read over the selection counts: the AI
    events of traces past the test account filters and the support rule, in the group and session it names. Which
    trace each one counts for is `period_membership`'s. Leaves out the trace search."""
    return _event_condition(team, replace(selection, search=None))


def _membership_events(team: Team, selection: TraceSelection, window: TraceWindow) -> ast.Expr:
    return _event_condition(
        team, replace(selection, window=window, filter_test_accounts=False, include_support_traces=True, search=None)
    )


def _in_traces_holding(events: ast.Expr, holding: ast.Expr) -> ast.Expr:
    """The events of the traces with an event that both `events` and `holding` match, matched by a hash of the trace
    id, so a trace whose hash collides with a matching trace's passes too."""
    # A trace's events can sit on several shards, so the shards all match against one set the initiator reads.
    # Probing every event against a hash set costs far less than against a set of trace id strings.
    trace_hash = parse_expr("cityHash64(properties.$ai_trace_id)")
    return ast.CompareOperation(
        op=ast.CompareOperationOp.GlobalIn,
        left=trace_hash,
        right=parse_select(
            "SELECT DISTINCT {trace_hash} FROM events WHERE {events} AND {holding}",
            placeholders={"trace_hash": trace_hash, "events": events, "holding": holding},
        ),
    )


def _in_period(team: Team, selection: TraceSelection, window: TraceWindow, in_bounds: ast.Expr) -> ast.Expr:
    def any_event(condition: ast.Expr) -> ast.Expr:
        return parse_expr(
            "countIf({in_bounds} AND {condition}) > 0", placeholders={"in_bounds": in_bounds, "condition": condition}
        )

    return _all(
        [
            any_event(parse_expr("event IN {events}", placeholders={"events": _events_in(TRACE_EVENT_NAMES)})),
            any_event(_all(_property_filters(team, selection))),
            *(any_event(event) for event in _trace_scope_events(selection)),
            parse_expr(
                "minIf(timestamp, {in_bounds}) <= {end} AND maxIf(timestamp, {in_bounds}) >= {start}",
                placeholders={
                    "in_bounds": in_bounds,
                    "start": ast.Constant(value=window.start),
                    "end": ast.Constant(value=window.end),
                },
            ),
        ]
    )


def period_membership(
    team: Team, selection: TraceSelection, previous: TraceWindow | None, *, holding: ast.Expr | None
) -> ast.SelectQuery:
    """One row per trace of the selection's window or of `previous`, with `trace_id`, `in_current` and
    `in_previous`, under the traces list's rules for each window. With `holding`, only the traces with an event
    `holding` matches, matched by a hash of the trace id, so a caller joins the rows back by the trace id itself.

    It reads only the trace id, event and timestamp, so the test account filters and the support rule are left to
    the rows a read counts, and every event of a trace sets its span. Leaves out the trace search."""
    window = selection.window
    span = window if previous is None else TraceWindow(start=previous.start, end=window.end)
    events = [_membership_events(team, selection, span)]
    if holding is not None:
        # A trace kept by a hash collision adds nothing, because its rows are joined back by the trace id itself.
        events.append(_in_traces_holding(events[0], holding))
    after_current_start = parse_expr(
        "timestamp >= {start}", placeholders={"start": ast.Constant(value=window.read_bounds().start)}
    )
    query = parse_select(
        """
        SELECT properties.$ai_trace_id AS trace_id, {in_current} AS in_current, {in_previous} AS in_previous
        FROM events
        WHERE {events}
        GROUP BY trace_id
        HAVING in_current OR in_previous
        """,
        placeholders={
            "in_current": _in_period(team, selection, window, after_current_start),
            "in_previous": ast.Constant(value=False)
            if previous is None
            else _in_period(
                team,
                selection,
                previous,
                parse_expr("timestamp <= {end}", placeholders={"end": ast.Constant(value=previous.read_bounds().end)}),
            ),
            "events": _all(events),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def grouped_traces(team: Team, selection: TraceSelection, extra: dict[str, ast.Expr]) -> ast.SelectQuery:
    """One row per trace the selection holds, with `trace_id`, `first_timestamp`, `last_timestamp` and the `extra`
    per-trace aggregates. A trace belongs when it overlaps the window, so every read over it counts the same traces.

    One session's selection groups only the events that name the session, so its traces sit at the earliest of those
    and a page of the session never groups the rest of its traces' events."""
    event_condition = _event_condition(team, selection)
    scope_events = _trace_scope_events(selection)
    if scope_events:
        # Grouping only the traces one scope holds reads far less than grouping every trace in the window. The scope
        # tests below still decide: they drop a trace a hash collision lets through, and one another scope misses.
        event_condition = _all([event_condition, _in_traces_holding(counted_events(team, selection), scope_events[0])])
    query = parse_select(
        """
        SELECT
            properties.$ai_trace_id AS trace_id,
            min(timestamp) AS first_timestamp,
            max(timestamp) AS last_timestamp
        FROM events
        WHERE {event_condition}
        GROUP BY trace_id
        HAVING countIf(event IN {trace_events}) > 0
            AND countIf({filters}) > 0
            AND {trace_scopes}
            AND first_timestamp <= {window_end}
            AND last_timestamp >= {window_start}
        """,
        placeholders={
            "event_condition": event_condition,
            "trace_events": _events_in(TRACE_EVENT_NAMES),
            "filters": _all(_property_filters(team, selection)),
            "trace_scopes": _all(_trace_scopes(selection)),
            "window_start": ast.Constant(value=selection.window.start),
            "window_end": ast.Constant(value=selection.window.end),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    query.select.extend(ast.Alias(alias=name, expr=expr) for name, expr in extra.items())
    return query


def load_trace_count(team: Team, user: User | None, selection: TraceSelection) -> int:
    """How many traces the traces list holds for the selection, before its quick filter."""
    query = parse_select("SELECT count() FROM {traces}", {"traces": grouped_traces(team, selection, {})})
    [[count]] = execute_selection(team, user, selection, query, TRACE_COUNT_QUERY_NAME)
    return count


def _page_source(team: Team, selection: TraceSelection) -> ast.SelectQuery:
    if selection.session_id is not None:
        return grouped_traces(team, selection, {})
    return grouped_traces(
        team,
        selection,
        {
            "has_error": trace_errored(EVENTS_COLUMNS, grouped),
            "has_feedback": parse_expr(
                "countIf(event IN {feedback_events}) > 0",
                placeholders={"feedback_events": _events_in(FEEDBACK_EVENT_NAMES)},
            ),
        },
    )


def _sort_key_ms(selection: TraceSelection) -> ast.Expr:
    # HogQL has no microsecond epoch function, so a page orders by the millisecond of the first event and breaks ties
    # by trace id, and the cursor compares on the same key.
    first_ms = parse_expr("toUnixTimestamp64Milli(first_timestamp)")
    if selection.order == "oldest_first":
        return first_ms
    return ast.Call(name="negate", args=[first_ms])


def _key(selection: TraceSelection) -> ast.Tuple:
    return ast.Tuple(exprs=[_sort_key_ms(selection), ast.Field(chain=["trace_id"])])


def _position_key(selection: TraceSelection, position: TracePosition) -> ast.Tuple:
    sort_key = position.sort_key if selection.order == "oldest_first" else -position.sort_key
    return ast.Tuple(exprs=[ast.Constant(value=sort_key), ast.Constant(value=position.trace_id)])


def _compare_key(selection: TraceSelection, op: ast.CompareOperationOp, bound: ast.Expr) -> ast.CompareOperation:
    return ast.CompareOperation(op=op, left=_key(selection), right=bound)


def _quick_filter_fact(selection: TraceSelection) -> list[ast.Expr]:
    if selection.quick_filter is None:
        return []
    return [ast.Field(chain=[_QUICK_FILTER_FACTS[selection.quick_filter]])]


def _counted(selection: TraceSelection) -> bool:
    return selection.session_id is None


def _rows_after_query(
    team: Team, selection: TraceSelection, after: TracePosition | None, take: int
) -> ast.SelectQuery | ast.SelectSetQuery:
    counted = _counted(selection)
    in_page = _quick_filter_fact(selection)
    at_or_before_bound: ast.Expr = ast.Constant(value=False)
    if after is not None:
        bound = _position_key(selection, after)
        in_page.append(_compare_key(selection, ast.CompareOperationOp.Gt, bound))
        at_or_before_bound = _all(
            [*_quick_filter_fact(selection), _compare_key(selection, ast.CompareOperationOp.LtEq, bound)]
        )
    return parse_select(
        """
        SELECT
            groupArraySortedIf({take})(tuple({sort_key_ms}, trace_id, first_timestamp), {in_page}) AS page,
            {total} AS total,
            {errors} AS errors,
            {feedback} AS feedback,
            argMaxIf(tuple(trace_id, first_timestamp), {key}, {at_or_before_bound}) AS previous,
            countIf({at_or_before_bound}) > 0 AS has_previous
        FROM {traces}
        """,
        placeholders={
            "take": ast.Constant(value=take),
            "sort_key_ms": _sort_key_ms(selection),
            "key": _key(selection),
            "in_page": _all(in_page),
            "total": parse_expr("count()") if counted else ast.Constant(value=None),
            "errors": parse_expr("countIf(has_error)") if counted else ast.Constant(value=None),
            "feedback": parse_expr("countIf(has_feedback)") if counted else ast.Constant(value=None),
            "at_or_before_bound": at_or_before_bound,
            "traces": _page_source(team, selection),
        },
    )


def _rows_before_query(team: Team, selection: TraceSelection, before: TracePosition, take: int) -> ast.SelectQuery:
    query = parse_select(
        """
        SELECT trace_id, first_timestamp
        FROM {traces}
        WHERE {before_bound}
        ORDER BY {sort_key_ms} DESC, trace_id DESC
        LIMIT {take}
        """,
        placeholders={
            "traces": _page_source(team, selection),
            "before_bound": _all(
                [
                    *_quick_filter_fact(selection),
                    _compare_key(selection, ast.CompareOperationOp.Lt, _position_key(selection, before)),
                ]
            ),
            "sort_key_ms": _sort_key_ms(selection),
            "take": ast.Constant(value=take),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _keyed_traces(team: Team, selection: TraceSelection) -> ast.SelectQuery:
    query = parse_select(
        "SELECT trace_id, first_timestamp, {sort_key_ms} AS sort_key FROM {traces} WHERE {quick_filter}",
        placeholders={
            "sort_key_ms": _sort_key_ms(selection),
            "traces": _page_source(team, selection),
            "quick_filter": _all(_quick_filter_fact(selection)),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _rows_around_query(team: Team, selection: TraceSelection, trace_id: str, takes: AroundTakes) -> ast.SelectQuery:
    # The anchor's key is read first, so each side is a top-N read and no side sorts the whole selection. A missing
    # anchor has a null key, which leaves the before side empty.
    anchor = ast.Constant(value=trace_id)
    anchor_sort_key = parse_select(
        "SELECT sort_key FROM {keyed} WHERE trace_id = {anchor}",
        placeholders={"keyed": _keyed_traces(team, selection), "anchor": anchor},
    )
    query = parse_select(
        """
        SELECT before_anchor, trace_id, first_timestamp, sort_key
        FROM (
            SELECT * FROM (
                SELECT true AS before_anchor, trace_id, first_timestamp, sort_key
                FROM {keyed}
                WHERE tuple(sort_key, trace_id) < tuple({anchor_sort_key}, {anchor})
                ORDER BY sort_key DESC, trace_id DESC
                LIMIT {before}
            )
            UNION ALL
            SELECT * FROM (
                SELECT false AS before_anchor, trace_id, first_timestamp, sort_key
                FROM {keyed}
                WHERE isNull({anchor_sort_key}) OR tuple(sort_key, trace_id) >= tuple({anchor_sort_key}, {anchor})
                ORDER BY sort_key ASC, trace_id ASC
                LIMIT {from_anchor}
            )
        )
        LIMIT {both_sides}
        """,
        placeholders={
            "keyed": _keyed_traces(team, selection),
            "anchor_sort_key": anchor_sort_key,
            "anchor": anchor,
            "before": ast.Constant(value=takes.before),
            "from_anchor": ast.Constant(value=takes.from_anchor),
            "both_sides": ast.Constant(value=takes.before + takes.from_anchor),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _reads_beyond_posthog_tables(prop: Mapping[str, Any]) -> bool:
    # A virtual revenue property is computed from the project's revenue views, which only the full catalog holds.
    return prop.get("type") in _QUERY_SCOPED_FILTER_TYPES or str(prop.get("key", "")).startswith(
        _VIRTUAL_PROPERTY_PREFIX
    )


def selection_database(team: Team, selection: TraceSelection) -> Database | None:
    """The catalog of PostHog's own tables, which skips loading every warehouse table, when no filter of the selection
    reads beyond them. None when one does, so the read loads the full catalog."""
    test_account_filters = (team.test_account_filters or []) if filters_test_accounts(team, selection) else []
    filters = [prop.model_dump() for prop in selection.properties] + list(test_account_filters)
    if any(_reads_beyond_posthog_tables(prop) for prop in filters):
        return None
    return Database.create_for_posthog_tables(team, group_types=get_group_types_for_project(team.project_id))


def execute_selection(
    team: Team,
    user: User | None,
    selection: TraceSelection,
    query: ast.SelectQuery | ast.SelectSetQuery,
    name: str,
    *,
    list_time_limit: bool = True,
) -> list[Any]:
    """Runs a read over the selection's traces with the catalog its filters need. A list's read stops at the lists'
    time limit, and any other read at the general query time limit. Either fails at its limit, and never answers
    from the part it read."""
    settings = HogQLGlobalSettings(timeout_overflow_mode="throw")
    if list_time_limit:
        settings.max_execution_time = _SELECTION_QUERY_SECONDS
    with tags_context(product=Product.LLM_ANALYTICS):
        tag_queries(name=name)
        response = execute_hogql_query(
            query=query,
            team=team,
            user=user,
            query_type=name,
            workload=Workload.ONLINE,
            context=HogQLContext(
                team_id=team.pk,
                user=user,
                database=selection_database(team, selection),
                property_type_overrides=EVENTS_FALLBACK_PROPERTY_TYPE_OVERRIDES,
            ),
            settings=settings,
        )
    return list(response.results or [])


def _query_name(selection: TraceSelection, suffix: str = "") -> str:
    base = SESSION_SELECTION_QUERY_NAME if selection.session_id is not None else SELECTION_QUERY_NAME
    return f"{base}{suffix}"


def _position(trace_id: str, first_timestamp: datetime) -> TracePosition:
    return TracePosition(trace_id=trace_id, first_timestamp=first_timestamp.astimezone(UTC))


def load_rows_after(
    team: Team, user: User | None, selection: TraceSelection, *, after: TracePosition | None, take: int
) -> SelectionRead:
    """Up to `take` of the selection's rows after `after` in its order, or from its first row, with the nearest row at
    or before `after` and the selection's counts. One session's selection reads no counts."""
    [[page, total, errors, feedback, (previous_id, previous_first), has_previous]] = execute_selection(
        team, user, selection, _rows_after_query(team, selection, after, take), _query_name(selection)
    )
    return SelectionRead(
        rows=RowsAfter(
            positions=tuple(_position(trace_id, first_timestamp) for _, trace_id, first_timestamp in page),
            previous=_position(previous_id, previous_first) if has_previous else None,
        ),
        counts=SelectionCounts(total=total, errors=errors, feedback=feedback) if _counted(selection) else None,
    )


def load_rows_before(
    team: Team, user: User | None, selection: TraceSelection, *, before: TracePosition, take: int
) -> RowsBefore:
    """Up to `take` of the selection's rows before `before` in its order, the nearest first."""
    results = execute_selection(
        team,
        user,
        selection,
        _rows_before_query(team, selection, before, take),
        _query_name(selection, BEFORE_QUERY_SUFFIX),
    )
    return RowsBefore(positions=tuple(_position(trace_id, first_timestamp) for trace_id, first_timestamp in results))


def load_rows_around(
    team: Team, user: User | None, selection: TraceSelection, *, trace_id: str, takes: AroundTakes
) -> RowsAround:
    """Up to `takes.before` of the selection's rows before the trace, the nearest first, and up to `takes.from_anchor`
    rows from the trace on, in one read that finds the trace by its id. Without the trace in the selection, the rows
    from the selection's first row on."""
    results = execute_selection(
        team,
        user,
        selection,
        _rows_around_query(team, selection, trace_id, takes),
        _query_name(selection, AROUND_QUERY_SUFFIX),
    )
    # Rows arrive in no set order, so each side is put back in key order.
    before = sorted((row for row in results if row[0]), key=lambda row: (row[3], row[1]), reverse=True)
    from_anchor = sorted((row for row in results if not row[0]), key=lambda row: (row[3], row[1]))
    return RowsAround(
        before=tuple(_position(row[1], row[2]) for row in before),
        from_anchor=tuple(_position(row[1], row[2]) for row in from_anchor),
    )
