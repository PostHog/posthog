from collections.abc import Mapping, Sequence
from datetime import UTC
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

from .trace_queries import FEEDBACK_EVENT_NAMES, TRACE_EVENT_NAMES
from .trace_selection import (
    QUERY_SCOPED_FILTERS,
    InvalidTraceSelectionError,
    QuickFilter,
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
_QUERY_SCOPED_FILTER_TYPES = frozenset(cls.model_fields["type"].default for cls in QUERY_SCOPED_FILTERS)
_VIRTUAL_PROPERTY_PREFIX = "$virt_"


@frozen
class SelectionCounts:
    total: int
    errors: int
    feedback: int


@frozen
class SelectionPage:
    positions: tuple[TracePosition, ...]
    has_more: bool
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
    search = (selection.search or "").strip()
    if search:
        exprs.append(_search_filter(team, selection, search))
    return _all(exprs)


def _in_page(selection: TraceSelection, after: TracePosition | None) -> ast.Expr:
    exprs: list[ast.Expr] = []
    if selection.quick_filter is not None:
        exprs.append(ast.Field(chain=[_QUICK_FILTER_FACTS[selection.quick_filter]]))
    if after is not None:
        exprs.append(
            parse_expr(
                """
                toUnixTimestamp64Milli(first_timestamp) < {after_ms}
                OR (toUnixTimestamp64Milli(first_timestamp) = {after_ms} AND trace_id > {after_id})
                """,
                placeholders={
                    "after_ms": ast.Constant(value=after.sort_key),
                    "after_id": ast.Constant(value=after.trace_id),
                },
            )
        )
    return _all(exprs)


def _selection_query(
    team: Team, selection: TraceSelection, after: TracePosition | None, limit: int
) -> ast.SelectQuery | ast.SelectSetQuery:
    # HogQL has no microsecond epoch function, so a page orders by the millisecond of the first event and breaks ties
    # by trace id, and the cursor compares on the same key.
    return parse_select(
        """
        SELECT
            groupArraySortedIf({take})(
                tuple(negate(toUnixTimestamp64Milli(first_timestamp)), trace_id, first_timestamp),
                {in_page}
            ) AS page,
            count() AS total,
            countIf(has_error) AS errors,
            countIf(has_feedback) AS feedback
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
            "take": ast.Constant(value=limit + 1),
            "in_page": _in_page(selection, after),
            "feedback_events": _events_in(FEEDBACK_EVENT_NAMES),
            "event_condition": _event_condition(team, selection),
            "trace_events": _events_in(TRACE_EVENT_NAMES),
            "membership": _all(_property_filters(team, selection)),
            "window_start": ast.Constant(value=selection.window.start),
            "window_end": ast.Constant(value=selection.window.end),
        },
    )


def _reads_beyond_posthog_tables(prop: Mapping[str, Any]) -> bool:
    # A virtual revenue property is computed from the project's revenue views, which only the full catalog holds.
    return prop.get("type") in _QUERY_SCOPED_FILTER_TYPES or str(prop.get("key", "")).startswith(
        _VIRTUAL_PROPERTY_PREFIX
    )


def _database(team: Team, selection: TraceSelection) -> Database | None:
    test_account_filters = (team.test_account_filters or []) if filters_test_accounts(team, selection) else []
    filters = [prop.model_dump() for prop in selection.properties] + list(test_account_filters)
    if any(_reads_beyond_posthog_tables(prop) for prop in filters):
        return None
    return Database.create_for_posthog_tables(team, group_types=get_group_types_for_project(team.project_id))


def load_selection_page(
    team: Team, user: User | None, selection: TraceSelection, *, after: TracePosition | None, limit: int
) -> SelectionPage:
    with tags_context(product=Product.LLM_ANALYTICS):
        tag_queries(name=SELECTION_QUERY_NAME)
        response = execute_hogql_query(
            query=_selection_query(team, selection, after, limit),
            team=team,
            user=user,
            query_type=SELECTION_QUERY_NAME,
            workload=Workload.ONLINE,
            context=HogQLContext(
                team_id=team.pk,
                user=user,
                database=_database(team, selection),
                property_type_overrides=EVENTS_FALLBACK_PROPERTY_TYPE_OVERRIDES,
            ),
            settings=HogQLGlobalSettings(max_execution_time=_SELECTION_QUERY_SECONDS, timeout_overflow_mode="throw"),
        )
    page, total, errors, feedback = response.results[0]
    return SelectionPage(
        positions=tuple(
            TracePosition(trace_id=trace_id, first_timestamp=first_timestamp.astimezone(UTC))
            for _, trace_id, first_timestamp in page[:limit]
        ),
        has_more=len(page) > limit,
        counts=SelectionCounts(total=total, errors=errors, feedback=feedback),
    )
