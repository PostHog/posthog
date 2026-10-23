from datetime import datetime, timedelta

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tag_queries, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.models import Team, User

from .trace_listing import (
    TraceFilters,
    TracePosition,
    TraceWindow,
    read_window,
    resolve_date_range,
    trace_positions_query,
)

NEIGHBOUR_WINDOW = timedelta(days=3)


@frozen
class Neighbours:
    older: TracePosition | None
    newer: TracePosition | None


def neighbour_window(created_at: datetime, list_range: TraceWindow | None) -> TraceWindow | None:
    start = created_at - NEIGHBOUR_WINDOW
    end = created_at + NEIGHBOUR_WINDOW
    if list_range is not None:
        start = max(start, list_range.start)
        end = min(end, list_range.end)
    return TraceWindow(start=start, end=end) if start <= end else None


def is_usable_anchor(created_at: datetime) -> bool:
    try:
        window = neighbour_window(created_at, None)
        assert window is not None
        read_window(window)
    except OverflowError:
        return False
    return True


def _neighbours_query(anchor: TracePosition, positions: ast.SelectQuery) -> ast.SelectQuery:
    query = parse_select(
        """
        SELECT
            argMaxIf(trace_id, (first_timestamp, trace_id), (first_timestamp, trace_id) < ({at}, {id})),
            maxIf(first_timestamp, (first_timestamp, trace_id) < ({at}, {id})),
            argMinIf(trace_id, (first_timestamp, trace_id), (first_timestamp, trace_id) > ({at}, {id})),
            minIf(first_timestamp, (first_timestamp, trace_id) > ({at}, {id}))
        FROM {positions}
        WHERE trace_id != {id}
        """,
        placeholders={
            "at": ast.Constant(value=anchor.first_timestamp),
            "id": ast.Constant(value=anchor.trace_id),
            "positions": positions,
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _position(trace_id: str | None, first_timestamp: datetime) -> TracePosition | None:
    return TracePosition(trace_id=trace_id, first_timestamp=first_timestamp) if trace_id else None


def load_neighbours(
    team: Team, user: User | None, anchor: TracePosition, filters: TraceFilters, now: datetime
) -> Neighbours:
    window = neighbour_window(anchor.first_timestamp, resolve_date_range(team, filters.date_from, filters.date_to, now))
    if window is None:
        return Neighbours(older=None, newer=None)
    name = "ai_trace_neighbours"
    with tags_context(product=Product.LLM_ANALYTICS):
        tag_queries(name=name)
        response = execute_hogql_query(
            query=_neighbours_query(anchor, trace_positions_query(team, filters, window)),
            team=team,
            user=user,
            query_type=name,
            workload=Workload.ONLINE,
        )
    older_id, older_at, newer_id, newer_at = response.results[0]
    return Neighbours(older=_position(older_id, older_at), newer=_position(newer_id, newer_at))
