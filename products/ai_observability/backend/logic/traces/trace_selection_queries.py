from collections.abc import Sequence
from datetime import UTC

from posthog.schema import AnyPropertyFilterDiscriminated, EventPropertyFilter

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
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

from .trace_queries import FEEDBACK_EVENT_NAMES, TRACE_EVENT_NAMES
from .trace_selection import (
    InvalidTraceSelectionError,
    QuickFilter,
    TracePageBounds,
    TracePosition,
    TraceSelection,
    filters_test_accounts,
)

SELECTION_QUERY_NAME = "ai_traces_selection"
# Recency-ordered cap on the traces a search matches: older matches drop once a search hits more than this.
SEARCH_CANDIDATE_TRACE_LIMIT = 100_000
AI_TRACE_EVENTS = (*TRACE_EVENT_NAMES, *FEEDBACK_EVENT_NAMES)
_SELECTION_QUERY_SECONDS = 30
_QUICK_FILTER_FACTS: dict[QuickFilter, str] = {"errors": "has_error", "feedback": "has_feedback"}


@frozen
class SelectionCounts:
    total: int
    errors: int
    feedback: int


@frozen
class SelectionPage:
    positions: tuple[TracePosition, ...]
    has_more: bool
    has_before: bool
    counts: SelectionCounts


def _all(exprs: Sequence[ast.Expr]) -> ast.Expr:
    return ast.And(exprs=list(exprs)) if exprs else ast.Constant(value=True)


def _escape_like_pattern(term: str) -> str:
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _person_scope(selection: TraceSelection) -> list[ast.Expr]:
    if selection.person_id is None:
        return []
    return [parse_expr("person_id = {person_id}", placeholders={"person_id": ast.Constant(value=selection.person_id)})]


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
        exprs.append(
            parse_expr("isNull(properties.ai_support_impersonated) OR properties.ai_support_impersonated != 'true'")
        )
    exprs.extend(_person_scope(selection))
    exprs.extend(_group_scope(selection))
    if selection.session_id is not None:
        exprs.append(
            parse_expr(
                "properties.$ai_session_id = {session_id}",
                placeholders={"session_id": ast.Constant(value=selection.session_id)},
            )
        )
    search = (selection.search or "").strip()
    if search:
        exprs.append(_search_filter(team, selection, search))
    return _all(exprs)


def _sort_key_ms(selection: TraceSelection) -> ast.Expr:
    first_ms = parse_expr("toUnixTimestamp64Milli(first_timestamp)")
    if selection.order == "oldest_first":
        return first_ms
    return ast.Call(name="negate", args=[first_ms])


def _position_key(selection: TraceSelection, position: TracePosition) -> ast.Tuple:
    sort_key = position.sort_key if selection.order == "oldest_first" else -position.sort_key
    return ast.Tuple(exprs=[ast.Constant(value=sort_key), ast.Constant(value=position.trace_id)])


def _beyond(selection: TraceSelection, position: TracePosition, op: ast.CompareOperationOp) -> ast.Expr:
    return ast.CompareOperation(
        op=op,
        left=ast.Tuple(exprs=[_sort_key_ms(selection), ast.Field(chain=["trace_id"])]),
        right=_position_key(selection, position),
    )


def _after_bound(selection: TraceSelection, after: TracePosition) -> ast.Expr:
    return _beyond(selection, after, ast.CompareOperationOp.Gt)


def _before_bound(selection: TraceSelection, before: TracePosition) -> ast.Expr:
    return _beyond(selection, before, ast.CompareOperationOp.Lt)


def _quick_filter_fact(selection: TraceSelection) -> list[ast.Expr]:
    if selection.quick_filter is None:
        return []
    return [ast.Field(chain=[_QUICK_FILTER_FACTS[selection.quick_filter]])]


def _in_page(selection: TraceSelection, bounds: TracePageBounds, trace_id: str | None) -> ast.Expr:
    exprs = _quick_filter_fact(selection)
    if bounds.after is not None:
        exprs.append(_after_bound(selection, bounds.after))
    if bounds.before is not None:
        exprs.append(_before_bound(selection, bounds.before))
    if trace_id is not None:
        exprs.append(
            parse_expr("trace_id = {trace_id}", placeholders={"trace_id": ast.Constant(value=trace_id)}),
        )
    return _all(exprs)


def _in_earlier_page(selection: TraceSelection, bounds: TracePageBounds) -> ast.Expr:
    """Rows that sort before the page: at or before the `after` bound. A `before` read gets this from its extra row."""
    if bounds.after is None:
        return ast.Constant(value=False)
    return _all([*_quick_filter_fact(selection), ast.Not(expr=_after_bound(selection, bounds.after))])


def _reads_backwards(bounds: TracePageBounds) -> bool:
    return bounds.before is not None and bounds.after is None


def _page_aggregate(selection: TraceSelection, bounds: TracePageBounds, trace_id: str | None, take: int) -> ast.Expr:
    key = "tuple({sort_key_ms}, trace_id, first_timestamp)"
    placeholders = {
        "take": ast.Constant(value=take),
        "sort_key_ms": _sort_key_ms(selection),
        "in_page": _in_page(selection, bounds, trace_id),
    }
    if _reads_backwards(bounds):
        # groupArraySorted only sorts ascending, and the trace id tie break has to descend with the rest of the key.
        return parse_expr(
            f"arraySlice(arrayReverse(arraySort(groupArrayIf({key}, {{in_page}}))), 1, {{take}})",
            placeholders=placeholders,
        )
    return parse_expr(f"groupArraySortedIf({{take}})({key}, {{in_page}})", placeholders=placeholders)


def _selection_query(
    team: Team, selection: TraceSelection, bounds: TracePageBounds, limit: int, trace_id: str | None = None
) -> ast.SelectQuery | ast.SelectSetQuery:
    # HogQL has no microsecond epoch function, so a page orders by the millisecond of the first event and breaks ties
    # by trace id, and the cursor compares on the same key.
    counted = selection.session_id is None and trace_id is None
    return parse_select(
        """
        SELECT
            {page} AS page,
            {total} AS total,
            {errors} AS errors,
            {feedback} AS feedback,
            {has_earlier} AS has_earlier
        FROM (
            SELECT
                properties.$ai_trace_id AS trace_id,
                min(timestamp) AS first_timestamp,
                max(timestamp) AS last_timestamp,
                countIf(properties.$ai_is_error = 'true') > 0 AS has_error,
                countIf(event IN {feedback_events}) > 0 AS has_feedback
            FROM events
            WHERE {event_condition}
            GROUP BY trace_id
            HAVING countIf(event IN {trace_events}) > 0
                AND countIf({membership}) > 0
                AND first_timestamp <= {window_end}
                AND last_timestamp >= {window_start}
        )
        """,
        placeholders={
            "page": _page_aggregate(selection, bounds, trace_id, limit + 1),
            "total": parse_expr("count()") if counted else ast.Constant(value=0),
            "errors": parse_expr("countIf(has_error)") if counted else ast.Constant(value=0),
            "feedback": parse_expr("countIf(has_feedback)") if counted else ast.Constant(value=0),
            "has_earlier": ast.Call(name="countIf", args=[_in_earlier_page(selection, bounds)]),
            "feedback_events": _events_in(FEEDBACK_EVENT_NAMES),
            "event_condition": _event_condition(team, selection),
            "trace_events": _events_in(TRACE_EVENT_NAMES),
            "membership": _all(_property_filters(team, selection)),
            "window_start": ast.Constant(value=selection.window.start),
            "window_end": ast.Constant(value=selection.window.end),
        },
    )


def _execute(
    team: Team,
    user: User | None,
    selection: TraceSelection,
    bounds: TracePageBounds,
    limit: int,
    trace_id: str | None = None,
) -> SelectionPage:
    with tags_context(product=Product.LLM_ANALYTICS):
        tag_queries(name=SELECTION_QUERY_NAME)
        response = execute_hogql_query(
            query=_selection_query(team, selection, bounds, limit, trace_id),
            team=team,
            user=user,
            query_type=SELECTION_QUERY_NAME,
            workload=Workload.ONLINE,
            context=HogQLContext(
                team_id=team.pk, user=user, property_type_overrides=EVENTS_FALLBACK_PROPERTY_TYPE_OVERRIDES
            ),
            settings=HogQLGlobalSettings(max_execution_time=_SELECTION_QUERY_SECONDS, timeout_overflow_mode="throw"),
        )
    page, total, errors, feedback, earlier_rows = response.results[0]
    has_more = len(page) > limit
    positions = [
        TracePosition(trace_id=row_trace_id, first_timestamp=first_timestamp.astimezone(UTC))
        for _, row_trace_id, first_timestamp in page[:limit]
    ]
    if _reads_backwards(bounds):
        positions.reverse()
    return SelectionPage(
        positions=tuple(positions),
        has_more=has_more,
        has_before=has_more if _reads_backwards(bounds) else earlier_rows > 0,
        counts=SelectionCounts(total=total, errors=errors, feedback=feedback),
    )


def load_selection_page(
    team: Team, user: User | None, selection: TraceSelection, *, bounds: TracePageBounds, limit: int
) -> SelectionPage:
    return _execute(team, user, selection, bounds, limit)


def load_trace_position(
    team: Team, user: User | None, selection: TraceSelection, trace_id: str
) -> TracePosition | None:
    page = _execute(team, user, selection, TracePageBounds(after=None, before=None), 1, trace_id)
    return page.positions[0] if page.positions else None
