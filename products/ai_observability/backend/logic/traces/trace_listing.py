from datetime import UTC, datetime, timedelta

from posthog.schema import AnyPropertyFilterDiscriminated, DateRange, IntervalType

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.property import property_to_expr

from posthog.dataclasses import frozen
from posthog.hogql_queries.ai.traces_query_runner import TracesQueryDateRange
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models import Team

AI_TRACE_EVENTS = ("$ai_span", "$ai_generation", "$ai_embedding", "$ai_metric", "$ai_feedback", "$ai_trace")
_UNBOUNDED_START = datetime.min.replace(tzinfo=UTC)
# The traces list reads this far past its range, so a trace that started just before the range keeps its real first
# event.
CAPTURE_BUFFER = timedelta(minutes=TracesQueryDateRange.CAPTURE_RANGE_MINUTES)


@frozen
class TraceFilters:
    date_from: str | None
    date_to: str | None
    properties: tuple[AnyPropertyFilterDiscriminated, ...]
    filter_test_accounts: bool
    include_support_traces: bool


@frozen
class TraceWindow:
    start: datetime
    end: datetime


@frozen
class TracePosition:
    trace_id: str
    first_timestamp: datetime


def read_window(window: TraceWindow) -> TraceWindow:
    """The events a window's traces are read from. Raises `OverflowError` near the ends of the datetime range."""
    return TraceWindow(
        start=window.start - CAPTURE_BUFFER if window.start > _UNBOUNDED_START else window.start,
        end=window.end + CAPTURE_BUFFER,
    )


class _ListDateRange(QueryDateRange):
    # The traces list ends a calendar-day `date_to` at the last moment of that day.
    CALENDAR_DAY_DATE_TO_IS_INCLUSIVE = True


def resolve_date_range(team: Team, date_from: str | None, date_to: str | None, now: datetime) -> TraceWindow | None:
    if not date_from and not date_to:
        return None
    # `all` would make the date range read the team's earliest event; the caller's window bounds the read instead.
    bounded_from = date_from if date_from != "all" else None
    date_range = _ListDateRange(DateRange(date_from=bounded_from, date_to=date_to), team, IntervalType.MINUTE, now)
    return TraceWindow(
        start=date_range.date_from() if bounded_from else _UNBOUNDED_START,
        end=date_range.date_to(),
    )


def _event_condition(team: Team, filters: TraceFilters, window: TraceWindow) -> ast.Expr:
    exprs: list[ast.Expr] = [
        parse_expr(
            "event IN {events} AND timestamp >= {start} AND timestamp <= {end} AND properties.$ai_trace_id != ''",
            placeholders={
                "events": ast.Tuple(exprs=[ast.Constant(value=event) for event in AI_TRACE_EVENTS]),
                "start": ast.Constant(value=window.start),
                "end": ast.Constant(value=window.end),
            },
        )
    ]
    if filters.filter_test_accounts:
        exprs.extend(property_to_expr(prop, team) for prop in team.test_account_filters or [])
    if not filters.include_support_traces:
        exprs.append(
            parse_expr("properties.ai_support_impersonated IS NULL OR properties.ai_support_impersonated != 'true'")
        )
    return ast.And(exprs=exprs)


def trace_positions_query(team: Team, filters: TraceFilters, window: TraceWindow) -> ast.SelectQuery:
    """Each trace with events in the window, at its first event as the traces list orders them. Property filters pick
    traces, they do not move them."""
    query = parse_select(
        """
        SELECT properties.$ai_trace_id AS trace_id, min(timestamp) AS first_timestamp
        FROM events
        WHERE {condition}
        GROUP BY trace_id
        HAVING countIf({membership}) > 0 AND first_timestamp <= {end} AND max(timestamp) >= {start}
        """,
        placeholders={
            "condition": _event_condition(team, filters, read_window(window)),
            "start": ast.Constant(value=window.start),
            "end": ast.Constant(value=window.end),
            "membership": ast.And(exprs=[property_to_expr(prop, team) for prop in filters.properties])
            if filters.properties
            else ast.Constant(value=True),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query
