from collections.abc import Sequence
from dataclasses import fields
from datetime import UTC, datetime, timedelta
from typing import Any

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

from .events_fallback import AI_EVENTS_RETENTION_DAYS, FallbackWindow, events_filter
from .trace_expressions import (
    AI_EVENTS_COLUMNS,
    BILLED_EVENT_NAMES,
    EVENTS_COLUMNS,
    TRACE_EVENT_NAMES,
    TraceColumns,
    grouped,
    trace_cost,
    trace_errored,
    trace_latency,
)
from .trace_queries import FEEDBACK_EVENT_NAMES, read_ai_events_table

SESSION_FACTS_QUERY_NAME = "ai_session_facts"
_SESSION_FACTS_QUERY_SECONDS = 30
_ACTIVITY_EVENT_NAMES = (*TRACE_EVENT_NAMES, *FEEDBACK_EVENT_NAMES)
_TRACE_COLUMN_NAMES = tuple(field.name for field in fields(TraceColumns))
_TOKEN_PROPERTIES = {
    "input_tokens": ("input_tokens", "$ai_input_tokens"),
    "output_tokens": ("output_tokens", "$ai_output_tokens"),
    "cache_read_tokens": ("cache_read_input_tokens", "$ai_cache_read_input_tokens"),
    "cache_write_tokens": ("cache_creation_input_tokens", "$ai_cache_creation_input_tokens"),
}


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
    distinct_id: str | None
    first_trace_id: str
    first_trace_created_at: datetime


@frozen
class _Layout:
    table: ast.Field
    source: TraceColumns
    session_id: ast.Expr
    tokens: dict[str, ast.Expr]


_AI_EVENTS_LAYOUT = _Layout(
    table=ast.Field(chain=["posthog", "ai_events"]),
    source=AI_EVENTS_COLUMNS,
    session_id=ast.Field(chain=["session_id"]),
    tokens={name: ast.Field(chain=[column]) for name, (column, _) in _TOKEN_PROPERTIES.items()},
)
_EVENTS_LAYOUT = _Layout(
    table=ast.Field(chain=["events"]),
    source=EVENTS_COLUMNS,
    session_id=ast.Field(chain=["properties", "$ai_session_id"]),
    tokens={
        name: ast.Call(name="toInt", args=[ast.Field(chain=["properties", prop])])
        for name, (_, prop) in _TOKEN_PROPERTIES.items()
    },
)
# The per-trace grouping reads the deduplicated rows, whose columns carry the same names on both layouts.
_DEDUPED = TraceColumns(**{name: ast.Field(chain=[name]) for name in _TRACE_COLUMN_NAMES})


def _names(names: Sequence[str]) -> ast.Tuple:
    return ast.Tuple(exprs=[ast.Constant(value=name) for name in names])


def _activity_events(layout: _Layout, include_support_traces: bool) -> ast.Expr:
    in_names = ast.CompareOperation(
        op=ast.CompareOperationOp.In, left=layout.source.event, right=_names(_ACTIVITY_EVENT_NAMES)
    )
    if include_support_traces:
        return in_names
    not_support = parse_expr(
        "isNull(properties.ai_support_impersonated) OR properties.ai_support_impersonated != 'true'"
    )
    return ast.And(exprs=[in_names, not_support])


def _since(layout: _Layout, moment: datetime) -> ast.Expr:
    return ast.CompareOperation(
        op=ast.CompareOperationOp.GtEq, left=layout.source.timestamp, right=ast.Constant(value=moment)
    )


def _traces_of_sessions(layout: _Layout, session_ids: Sequence[str], bounds: ast.Expr) -> ast.Expr:
    # A trace's events without a session id still belong to it, so the sessions select trace ids and not events.
    named = ast.CompareOperation(
        op=ast.CompareOperationOp.In, left=layout.session_id, right=ast.Constant(value=list(session_ids))
    )
    subquery = ast.SelectQuery(
        select=[layout.source.trace_id],
        select_from=ast.JoinExpr(table=layout.table),
        where=ast.And(exprs=[named, bounds]),
    )
    return ast.CompareOperation(op=ast.CompareOperationOp.GlobalIn, left=layout.source.trace_id, right=subquery)


def _deduped_events(layout: _Layout, where: ast.Expr) -> ast.SelectQuery:
    selected: dict[str, ast.Expr] = {
        "uuid": ast.Field(chain=["uuid"]),
        "session_id": layout.session_id,
        **layout.tokens,
        **{name: getattr(layout.source, name) for name in _TRACE_COLUMN_NAMES},
    }
    query = parse_select("SELECT 1 FROM events LIMIT 1 BY uuid")
    assert isinstance(query, ast.SelectQuery)
    query.select = [ast.Alias(alias=name, expr=expr) for name, expr in selected.items()]
    query.select_from = ast.JoinExpr(table=layout.table)
    query.where = where
    return query


def _per_trace(deduped: ast.SelectQuery, session_ids: Sequence[str]) -> ast.SelectQuery:
    billed = ast.CompareOperation(op=ast.CompareOperationOp.In, left=_DEDUPED.event, right=_names(BILLED_EVENT_NAMES))
    query = parse_select(
        """
        SELECT
            trace_id,
            arrayJoin(
                arrayIntersect(
                    groupUniqArrayIf(session_id, isNotNull(session_id) AND session_id != ''), {session_ids}
                )
            ) AS trace_session,
            minIf(timestamp, {is_trace_event}) AS trace_start,
            max(timestamp) AS trace_end,
            {latency} AS trace_latency_s,
            {errored} AS trace_has_error,
            {cost} AS trace_cost_usd,
            sumIf(input_tokens, {billed}) AS trace_input_tokens,
            sumIf(output_tokens, {billed}) AS trace_output_tokens,
            sumIf(cache_read_tokens, {billed}) AS trace_cache_read_tokens,
            sumIf(cache_write_tokens, {billed}) AS trace_cache_write_tokens,
            argMinIf(distinct_id, timestamp, {is_trace_event}) AS trace_distinct_id
        FROM {deduped}
        GROUP BY trace_id
        HAVING countIf({is_trace_event}) > 0
        """,
        placeholders={
            "latency": trace_latency(_DEDUPED, grouped),
            "errored": trace_errored(_DEDUPED, grouped),
            "cost": trace_cost(_DEDUPED, grouped),
            "billed": billed,
            "is_trace_event": ast.CompareOperation(
                op=ast.CompareOperationOp.In, left=_DEDUPED.event, right=_names(TRACE_EVENT_NAMES)
            ),
            "deduped": deduped,
            "session_ids": ast.Constant(value=list(session_ids)),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _facts_query(layout: _Layout, where: ast.Expr, session_ids: Sequence[str]) -> ast.SelectQuery:
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
            argMin(trace_distinct_id, trace_start) AS distinct_id,
            argMin(trace_id, trace_start) AS first_trace_id
        FROM {per_trace}
        GROUP BY trace_session
        """,
        placeholders={"per_trace": _per_trace(_deduped_events(layout, where), session_ids)},
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _ai_events_query(session_ids: Sequence[str], now: datetime, include_support_traces: bool) -> ast.SelectQuery:
    layout = _AI_EVENTS_LAYOUT
    within_retention = ast.And(
        exprs=[
            _activity_events(layout, include_support_traces),
            _since(layout, now - timedelta(days=AI_EVENTS_RETENTION_DAYS)),
        ]
    )
    where = ast.And(exprs=[within_retention, _traces_of_sessions(layout, session_ids, within_retention)])
    return _facts_query(layout, where, session_ids)


def _events_query(session_ids: Sequence[str], window: FallbackWindow, include_support_traces: bool) -> ast.SelectQuery:
    layout = _EVENTS_LAYOUT
    activity = _activity_events(layout, include_support_traces)
    in_window = events_filter(trace_filter=ast.Constant(value=True), event_filter=activity, window=window)
    where = events_filter(
        trace_filter=_traces_of_sessions(layout, session_ids, in_window), event_filter=activity, window=window
    )
    return _facts_query(layout, where, session_ids)


def _settings() -> HogQLGlobalSettings:
    return HogQLGlobalSettings(max_execution_time=_SESSION_FACTS_QUERY_SECONDS, timeout_overflow_mode="throw")


def _read_events(team: Team, user: User | None, query: ast.SelectQuery) -> list[Sequence[Any]]:
    with tags_context(product=Product.LLM_ANALYTICS):
        tag_queries(name=SESSION_FACTS_QUERY_NAME, ai_query_source="shared_table_fallback")
        response = execute_hogql_query(
            query=query,
            team=team,
            user=user,
            query_type=SESSION_FACTS_QUERY_NAME,
            workload=Workload.ONLINE,
            context=HogQLContext(
                team_id=team.pk, user=user, property_type_overrides=EVENTS_FALLBACK_PROPERTY_TYPE_OVERRIDES
            ),
            settings=_settings(),
        )
    return list(response.results or [])


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
        distinct_id,
        first_trace_id,
    ) = row
    first_seen, last_seen = first_seen.astimezone(UTC), last_seen.astimezone(UTC)
    return SessionFacts(
        session_id=session_id,
        first_seen=first_seen,
        last_seen=last_seen,
        duration_ms=float(duration_ms),
        turn_count=int(turn_count),
        cost_usd=_number(cost_usd),
        input_tokens=_count(input_tokens),
        output_tokens=_count(output_tokens),
        cache_read_tokens=_count(cache_read_tokens),
        cache_write_tokens=_count(cache_write_tokens),
        wait_ms=_number(wait_ms),
        errored_turns=int(errored_turns),
        distinct_id=distinct_id or None,
        first_trace_id=first_trace_id,
        first_trace_created_at=first_seen,
    )


def load_session_facts(
    team: Team,
    user: User | None,
    session_ids: Sequence[str],
    *,
    fallback: FallbackWindow | None = None,
    include_support_traces: bool = False,
) -> dict[str, SessionFacts]:
    wanted = list(dict.fromkeys(session_ids))
    if not wanted:
        return {}
    ai_rows = read_ai_events_table(
        SESSION_FACTS_QUERY_NAME,
        _ai_events_query(wanted, datetime.now(UTC), include_support_traces),
        team,
        user,
        _settings(),
    )
    found = {facts.session_id: facts for facts in map(_facts, ai_rows)}
    missing = [session_id for session_id in wanted if session_id not in found]
    if missing and fallback is not None:
        events_rows = _read_events(team, user, _events_query(missing, fallback, include_support_traces))
        found.update({facts.session_id: facts for facts in map(_facts, events_rows)})
    return found
