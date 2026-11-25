from datetime import UTC, datetime
from typing import Final

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.dataclasses import frozen
from posthog.models import Team, User

from .trace_expression_queries import EVENTS_COLUMNS, grouped, trace_session_ids
from .trace_selection import CursorPoint, InvalidTraceSelectionError, TraceSelection, decode_point, encode_point
from .trace_selection_queries import execute_selection, grouped_traces

SESSIONS_SELECTION_QUERY_NAME = "ai_sessions_selection"
_CURSOR_KIND = "session"
# The longest session id the list hands out, so that every listed session can be read by its id.
SESSION_ID_MAX_LENGTH: Final = 400


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
    return encode_point(CursorPoint(moment=position.last_timestamp, key=position.session_id), kind=_CURSOR_KIND)


def decode_session_cursor(cursor: str) -> SessionPosition:
    point = decode_point(cursor, kind=_CURSOR_KIND)
    return SessionPosition(session_id=point.key, last_timestamp=point.moment)


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
    traces = grouped_traces(team, selection, {"session_ids": trace_session_ids(EVENTS_COLUMNS, grouped)})
    query = parse_select(
        """
        SELECT session_id, max(last_timestamp) AS last_activity
        FROM (SELECT arrayJoin(session_ids) AS session_id, last_timestamp FROM {traces})
        WHERE lengthUTF8(session_id) <= {max_length}
        GROUP BY session_id
        HAVING {after}
        ORDER BY last_activity DESC, session_id ASC
        LIMIT {limit}
        """,
        placeholders={
            "traces": traces,
            "after": _after(after) if after is not None else ast.Constant(value=True),
            "limit": ast.Constant(value=limit + 1),
            "max_length": ast.Constant(value=SESSION_ID_MAX_LENGTH),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def load_session_page(
    team: Team, user: User | None, selection: TraceSelection, *, after: SessionPosition | None, limit: int
) -> SessionSelectionPage:
    if selection.session_id is not None:
        raise InvalidTraceSelectionError("A sessions list can't be scoped to one session.")
    results = execute_selection(
        team, user, selection, _sessions_query(team, selection, after, limit), SESSIONS_SELECTION_QUERY_NAME
    )
    positions = [
        SessionPosition(session_id=session_id, last_timestamp=last_activity.astimezone(UTC))
        for session_id, last_activity in results[:limit]
    ]
    return SessionSelectionPage(
        session_ids=tuple(position.session_id for position in positions),
        has_more=len(results) > limit,
        last_position=positions[-1] if positions else None,
    )
