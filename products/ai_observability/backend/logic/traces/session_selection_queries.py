import json
import base64
import binascii
from datetime import UTC, datetime, timedelta

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Product, tag_queries, tags_context
from posthog.dataclasses import frozen
from posthog.hogql_queries.ai.ai_column_rewriter import EVENTS_FALLBACK_PROPERTY_TYPE_OVERRIDES
from posthog.models import Team, User

from .trace_selection import InvalidTraceCursorError, InvalidTraceSelectionError, TraceSelection
from .trace_selection_queries import grouped_traces

SESSIONS_SELECTION_QUERY_NAME = "ai_sessions_selection"
_SESSIONS_QUERY_SECONDS = 30
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@frozen
class SessionPosition:
    session_id: str
    last_timestamp: datetime


@frozen
class SessionSelectionPage:
    session_ids: tuple[str, ...]
    has_more: bool
    last_position: SessionPosition | None


def encode_session_cursor(position: SessionPosition) -> str:
    microseconds = (position.last_timestamp.astimezone(UTC) - _EPOCH) // timedelta(microseconds=1)
    payload = json.dumps([microseconds, position.session_id], separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")


def decode_session_cursor(cursor: str) -> SessionPosition:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
        microseconds, session_id = payload
        if type(microseconds) is not int or not isinstance(session_id, str):
            raise ValueError("Unexpected cursor contents")
        return SessionPosition(session_id=session_id, last_timestamp=_EPOCH + timedelta(microseconds=microseconds))
    except (ValueError, TypeError, binascii.Error, OverflowError) as error:
        raise InvalidTraceCursorError("The cursor is not valid") from error


def _after(position: SessionPosition) -> ast.Expr:
    return parse_expr(
        "last_activity < {moment} OR (last_activity = {moment} AND session_id > {session_id})",
        placeholders={
            "moment": ast.Constant(value=position.last_timestamp.astimezone(UTC)),
            "session_id": ast.Constant(value=position.session_id),
        },
    )


def _sessions_query(
    team: Team, selection: TraceSelection, after: SessionPosition | None, limit: int
) -> ast.SelectQuery:
    # A trace's session is its earliest non-empty id, so a trace that switches ids counts toward one session only.
    traces = grouped_traces(
        team,
        selection,
        {"session_id": parse_expr("argMinIf(properties.$ai_session_id, timestamp, properties.$ai_session_id != '')")},
    )
    query = parse_select(
        """
        SELECT session_id, max(last_timestamp) AS last_activity
        FROM {traces}
        WHERE isNotNull(session_id) AND session_id != ''
        GROUP BY session_id
        HAVING {after}
        ORDER BY last_activity DESC, session_id ASC
        LIMIT {limit}
        """,
        placeholders={
            "traces": traces,
            "after": _after(after) if after is not None else ast.Constant(value=True),
            "limit": ast.Constant(value=limit + 1),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def load_session_page(
    team: Team, user: User | None, selection: TraceSelection, *, after: SessionPosition | None, limit: int
) -> SessionSelectionPage:
    if selection.session_id is not None:
        raise InvalidTraceSelectionError("A sessions list can't be scoped to one session.")
    with tags_context(product=Product.LLM_ANALYTICS):
        tag_queries(name=SESSIONS_SELECTION_QUERY_NAME)
        response = execute_hogql_query(
            query=_sessions_query(team, selection, after, limit),
            team=team,
            user=user,
            query_type=SESSIONS_SELECTION_QUERY_NAME,
            workload=Workload.ONLINE,
            context=HogQLContext(
                team_id=team.pk, user=user, property_type_overrides=EVENTS_FALLBACK_PROPERTY_TYPE_OVERRIDES
            ),
            settings=HogQLGlobalSettings(max_execution_time=_SESSIONS_QUERY_SECONDS, timeout_overflow_mode="throw"),
        )
    rows = response.results[:limit]
    positions = [
        SessionPosition(session_id=session_id, last_timestamp=last_activity.astimezone(UTC))
        for session_id, last_activity in rows
    ]
    return SessionSelectionPage(
        session_ids=tuple(position.session_id for position in positions),
        has_more=len(response.results) > limit,
        last_position=positions[-1] if positions else None,
    )
