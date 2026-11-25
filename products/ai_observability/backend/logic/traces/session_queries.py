from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Final

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select

from posthog.dataclasses import frozen
from posthog.models import Team, User

from .events_fallback import FallbackWindow
from .trace_expression_queries import (
    AI_EVENTS_COLUMNS,
    BILLED_EVENT_NAMES,
    TRACE_EVENT_NAMES,
    grouped,
    names_session,
    not_impersonated,
    trace_cost,
    trace_errored,
    trace_latency,
    trace_session_ids,
)
from .trace_queries import FEEDBACK_EVENT_NAMES, event_in, read_ai_events_table, read_shared_events_table

SESSION_FACTS_QUERY_NAME = "ai_session_facts"
# The cap binds a session id that a project reuses for everything, whose facts would otherwise time out the whole page.
SESSION_FACTS_MAX_TRACES: Final = 1000
_SESSION_FACTS_QUERY_SECONDS = 30
_ACTIVITY_EVENT_NAMES = (*TRACE_EVENT_NAMES, *FEEDBACK_EVENT_NAMES)
# Read once per event before the per-trace grouping, under the names the ai_events columns carry, which is what
# `AI_EVENTS_COLUMNS` reads.
_EVENT_COLUMNS = (
    "uuid",
    "event",
    "timestamp",
    "trace_id",
    "session_id",
    "parent_id",
    "latency",
    "is_error",
    "total_cost_usd",
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)


@frozen
class SessionFacts:
    session_id: str
    first_seen: datetime
    last_seen: datetime
    duration_ms: float | None
    turn_count: int
    cost_usd: float | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_write_tokens: int | None
    wait_ms: float | None
    errored_turns: int
    totals_partial: bool


def _field(name: str) -> ast.Field:
    return ast.Field(chain=[name])


def _within(start: datetime, end: datetime | None) -> list[ast.Expr]:
    bounds: list[ast.Expr] = [
        ast.CompareOperation(op=ast.CompareOperationOp.GtEq, left=_field("timestamp"), right=ast.Constant(value=start))
    ]
    if end is not None:
        bounds.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq, left=_field("timestamp"), right=ast.Constant(value=end)
            )
        )
    return bounds


@frozen
class _FactsRead:
    session_ids: Sequence[str]
    within: list[ast.Expr]
    max_traces: int
    # Support traces are left out either event by event, before the cap picks the recent traces, or trace by trace,
    # after it, which reads the support flag of the capped traces' events only.
    events_filter: list[ast.Expr]
    leaves_out_support_traces: bool


def _recent_traces(read: _FactsRead) -> ast.SelectQuery:
    # One trace past the cap tells a session that holds more traces than the facts cover.
    query = parse_select(
        """
        SELECT trace_id
        FROM posthog.ai_events
        WHERE {where} AND isNotNull(trace_id) AND trace_id != ''
        GROUP BY session_id, trace_id
        ORDER BY max(timestamp) DESC, trace_id DESC
        LIMIT {per_session} BY session_id
        """,
        placeholders={
            "where": ast.And(
                exprs=[
                    names_session(AI_EVENTS_COLUMNS, read.session_ids),
                    event_in(_ACTIVITY_EVENT_NAMES),
                    *read.within,
                    *read.events_filter,
                ]
            ),
            "per_session": ast.Constant(value=read.max_traces + 1),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _session_events(read: _FactsRead) -> ast.Expr:
    return ast.And(
        exprs=[
            event_in(_ACTIVITY_EVENT_NAMES),
            *read.within,
            ast.CompareOperation(
                op=ast.CompareOperationOp.GlobalIn, left=_field("trace_id"), right=_recent_traces(read)
            ),
            *read.events_filter,
        ]
    )


def _deduped_events(read: _FactsRead) -> ast.SelectQuery:
    query = parse_select("SELECT 1 FROM posthog.ai_events LIMIT 1 BY uuid")
    assert isinstance(query, ast.SelectQuery)
    impersonated = ast.Not(expr=not_impersonated()) if read.leaves_out_support_traces else ast.Constant(value=False)
    query.select = [*(_field(column) for column in _EVENT_COLUMNS), ast.Alias(alias="impersonated", expr=impersonated)]
    query.where = _session_events(read)
    return query


def _per_trace(session_ids: Sequence[str], deduped: ast.SelectQuery) -> ast.SelectQuery:
    columns = AI_EVENTS_COLUMNS
    query = parse_select(
        """
        SELECT
            trace_id,
            arrayJoin(arrayIntersect({session_ids_of_trace}, {session_ids})) AS trace_session,
            minIf(timestamp, {is_trace_event}) AS trace_start,
            max(timestamp) AS trace_end,
            {latency} AS trace_latency_s,
            {errored} AS trace_has_error,
            {cost} AS trace_cost_usd,
            sumIf(input_tokens, {billed}) AS trace_input_tokens,
            sumIf(output_tokens, {billed}) AS trace_output_tokens,
            sumIf(cache_read_input_tokens, {billed}) AS trace_cache_read_tokens,
            sumIf(cache_creation_input_tokens, {billed}) AS trace_cache_write_tokens,
            countIf(impersonated) > 0 AS trace_is_support
        FROM {deduped}
        GROUP BY trace_id
        HAVING countIf({is_trace_event}) > 0
        """,
        placeholders={
            "session_ids_of_trace": trace_session_ids(columns, grouped),
            "session_ids": ast.Constant(value=list(session_ids)),
            "latency": trace_latency(columns, grouped),
            "errored": trace_errored(columns, grouped),
            "cost": trace_cost(columns, grouped),
            "billed": event_in(BILLED_EVENT_NAMES),
            "is_trace_event": event_in(TRACE_EVENT_NAMES),
            "deduped": deduped,
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _facts_query(read: _FactsRead) -> ast.SelectQuery:
    per_trace = _per_trace(read.session_ids, _deduped_events(read))
    # A trace's latency may end after its last event, so the session runs to the latest end of either.
    query = parse_select(
        """
        SELECT
            trace_session AS session_id,
            min(trace_start) AS first_seen,
            max(trace_end) AS last_seen,
            max(
                greatest(
                    toFloat(toUnixTimestamp64Milli(trace_end)),
                    toUnixTimestamp64Milli(trace_start) + ifNull(trace_latency_s, 0) * 1000
                )
            ) - toUnixTimestamp64Milli(min(trace_start)) AS duration_ms,
            count() AS turn_count,
            sum(trace_cost_usd) AS cost_usd,
            sum(trace_input_tokens) AS input_tokens,
            sum(trace_output_tokens) AS output_tokens,
            sum(trace_cache_read_tokens) AS cache_read_tokens,
            sum(trace_cache_write_tokens) AS cache_write_tokens,
            sum(trace_latency_s) * 1000 AS wait_ms,
            countIf(trace_has_error) AS errored_turns,
            max(traces_in_session) > {max_traces} AS totals_partial
        FROM (
            SELECT
                trace_session,
                trace_start,
                trace_end,
                trace_latency_s,
                trace_has_error,
                trace_cost_usd,
                trace_input_tokens,
                trace_output_tokens,
                trace_cache_read_tokens,
                trace_cache_write_tokens,
                trace_is_support,
                row_number() OVER (PARTITION BY trace_session ORDER BY trace_end DESC, trace_id DESC) AS recency,
                count() OVER (PARTITION BY trace_session) AS traces_in_session
            FROM {per_trace}
        )
        WHERE recency <= {max_traces} AND NOT trace_is_support
        GROUP BY trace_session
        """,
        placeholders={"per_trace": per_trace, "max_traces": ast.Constant(value=read.max_traces)},
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _settings() -> HogQLGlobalSettings:
    return HogQLGlobalSettings(max_execution_time=_SESSION_FACTS_QUERY_SECONDS, timeout_overflow_mode="throw")


def _number(value: Any) -> float | None:
    return None if value is None else float(value)


def _count(value: Any) -> int | None:
    return None if value is None else int(value)


def _facts(row: Sequence[Any]) -> SessionFacts:
    (
        session_id,
        first_seen,
        last_seen,
        duration_ms,
        turn_count,
        cost_usd,
        input_tokens,
        output_tokens,
        cache_read_tokens,
        cache_write_tokens,
        wait_ms,
        errored_turns,
        totals_partial,
    ) = row
    return SessionFacts(
        session_id=session_id,
        first_seen=first_seen.astimezone(UTC),
        last_seen=last_seen.astimezone(UTC),
        duration_ms=float(duration_ms),
        turn_count=int(turn_count),
        cost_usd=_number(cost_usd),
        input_tokens=_count(input_tokens),
        output_tokens=_count(output_tokens),
        cache_read_tokens=_count(cache_read_tokens),
        cache_write_tokens=_count(cache_write_tokens),
        wait_ms=_number(wait_ms),
        errored_turns=int(errored_turns),
        totals_partial=bool(totals_partial),
    )


def _read_facts(rows: list[Sequence[Any]]) -> dict[str, SessionFacts]:
    return {facts.session_id: facts for facts in map(_facts, rows)}


def load_session_facts(
    team: Team,
    user: User | None,
    session_ids: Sequence[str],
    *,
    since: datetime,
    include_support_traces: bool = False,
) -> dict[str, SessionFacts]:
    """Each session's facts over its most recent `SESSION_FACTS_MAX_TRACES` traces, keyed by session id, from
    `posthog.ai_events` since `since`. A session it does not hold is left out."""
    wanted = list(dict.fromkeys(session_ids))
    if not wanted:
        return {}
    read = _FactsRead(
        session_ids=wanted,
        within=_within(since, None),
        max_traces=SESSION_FACTS_MAX_TRACES,
        events_filter=[] if include_support_traces else [not_impersonated()],
        leaves_out_support_traces=False,
    )
    return _read_facts(read_ai_events_table(SESSION_FACTS_QUERY_NAME, _facts_query(read), team, user, _settings()))


def load_shared_session_facts(
    team: Team,
    user: User | None,
    session_ids: Sequence[str],
    *,
    window: FallbackWindow,
    max_traces: int,
    include_support_traces: bool = False,
) -> dict[str, SessionFacts]:
    """Each session's facts over its most recent `max_traces` traces, keyed by session id, from the shared events
    table inside `window`. A session it does not hold is left out."""
    wanted = list(dict.fromkeys(session_ids))
    if not wanted:
        return {}
    read = _FactsRead(
        session_ids=wanted,
        within=_within(window.start, window.end),
        max_traces=max_traces,
        events_filter=[],
        leaves_out_support_traces=not include_support_traces,
    )
    return _read_facts(read_shared_events_table(SESSION_FACTS_QUERY_NAME, _facts_query(read), team, user, _settings()))
