from collections.abc import Sequence
from datetime import datetime
from typing import Final

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_select

from posthog.dataclasses import frozen
from posthog.models import Team, User

from .preview_queries import SourceReads
from .trace_expression_queries import (
    AI_EVENTS_COLUMNS,
    TRACE_EVENT_NAMES,
    grouped,
    names_session,
    not_impersonated,
    trace_person_id,
    trace_session_ids,
)
from .trace_queries import event_in, read_ai_events_table
from .trace_selection_queries import AI_TRACE_EVENTS

SESSION_TITLE_TRACES_QUERY_NAME = "ai_session_title_traces"
SESSION_PERSON_TRACES_QUERY_NAME = "ai_session_person_traces"
SESSION_TITLE_PICKS_QUERY_NAME = "ai_session_title_picks"
SESSION_TITLES_QUERY_NAME = "ai_session_titles"
SESSION_PEOPLE_QUERY_NAME = "ai_session_people"
SESSION_TITLE_READS: Final = SourceReads(
    picks_name=SESSION_TITLE_PICKS_QUERY_NAME, values_name=SESSION_TITLES_QUERY_NAME
)
# A trace whose first event names no session can start before a trace that names it earlier, so the first trace is
# chosen among a session's earliest few rather than the single earliest one.
FIRST_TRACE_CANDIDATES: Final = 20
_FIRST_TRACES_QUERY_SECONDS = 15


@frozen
class SessionFirstTrace:
    trace_id: str
    distinct_id: str | None


def _support_filter(include_support_traces: bool) -> list[ast.Expr]:
    return [] if include_support_traces else [not_impersonated()]


def _candidates(session_ids: Sequence[str], since: datetime, include_support_traces: bool) -> ast.SelectQuery:
    query = parse_select(
        """
        SELECT trace_id
        FROM posthog.ai_events
        WHERE {where} AND trace_id != ''
        GROUP BY session_id, trace_id
        ORDER BY min(timestamp), trace_id
        LIMIT {candidates} BY session_id
        """,
        placeholders={
            "where": ast.And(
                exprs=[
                    names_session(AI_EVENTS_COLUMNS, session_ids),
                    event_in(AI_TRACE_EVENTS),
                    parse_expr("timestamp >= {since}", placeholders={"since": ast.Constant(value=since)}),
                    *_support_filter(include_support_traces),
                ]
            ),
            "candidates": ast.Constant(value=FIRST_TRACE_CANDIDATES),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _first_traces_query(session_ids: Sequence[str], since: datetime, include_support_traces: bool) -> ast.SelectQuery:
    # A tuple is never null, so the first trace's missing person stays missing instead of falling to a later trace.
    # A feedback or metric event can be the only one that names the session, so those events are read for the trace's
    # sessions, while its start and its person come from its trace events.
    query = parse_select(
        """
        SELECT session_id, argMin(tuple(trace_id, trace_person), tuple(trace_start, trace_id))
        FROM (
            SELECT
                trace_id,
                arrayJoin(arrayIntersect({session_ids_of_trace}, {session_ids})) AS session_id,
                minIf(timestamp, {trace_events}) AS trace_start,
                {person} AS trace_person
            FROM posthog.ai_events
            WHERE {where}
            GROUP BY trace_id
            HAVING countIf({trace_events}) > 0
        )
        GROUP BY session_id
        """,
        placeholders={
            "session_ids_of_trace": trace_session_ids(AI_EVENTS_COLUMNS, grouped),
            "session_ids": ast.Constant(value=list(session_ids)),
            "trace_events": event_in(TRACE_EVENT_NAMES),
            "person": trace_person_id(AI_EVENTS_COLUMNS, grouped),
            "where": ast.And(
                exprs=[
                    event_in(AI_TRACE_EVENTS),
                    parse_expr("timestamp >= {since}", placeholders={"since": ast.Constant(value=since)}),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.GlobalIn,
                        left=ast.Field(chain=["trace_id"]),
                        right=_candidates(session_ids, since, include_support_traces),
                    ),
                    *_support_filter(include_support_traces),
                ]
            ),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def load_session_first_traces(
    team: Team,
    user: User | None,
    session_ids: Sequence[str],
    *,
    since: datetime,
    include_support_traces: bool,
    name: str,
) -> dict[str, SessionFirstTrace]:
    """Each session's first trace, the one whose first event came earliest, ties broken by trace id, keyed by session
    id. Reads only `posthog.ai_events` since `since`, so a session it no longer holds has no entry."""
    wanted = list(dict.fromkeys(session_ids))
    if not wanted:
        return {}
    rows = read_ai_events_table(
        name,
        _first_traces_query(wanted, since, include_support_traces),
        team,
        user,
        HogQLGlobalSettings(max_execution_time=_FIRST_TRACES_QUERY_SECONDS, timeout_overflow_mode="throw"),
    )
    return {
        str(session_id): SessionFirstTrace(trace_id=str(trace_id), distinct_id=str(person) if person else None)
        for session_id, (trace_id, person) in rows
    }
