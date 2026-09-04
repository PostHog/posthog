"""Candidate walk for evaluation backfills.

One HogQL query shape serves both the pre-start estimate and the paged dispatch, so the number
a user approves and the units the workflow evaluates come from the same predicate.
"""

from datetime import datetime
from typing import Any

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.dataclasses import frozen
from posthog.hogql_queries.ai.ai_table_resolver import AIEventsExpiredError, AIEventsNotFoundError, query_ai_events
from posthog.models.team import Team

from products.ai_observability.backend.models.evaluations import EvaluationTarget

# The count runs inside an API request and the walk inside one activity attempt, so a
# pathological filter must fail the caller rather than hold it for the 60s default.
MAX_EXECUTION_TIME_SECONDS = 30

CANDIDATE_QUERY_TYPE = "EvaluationBackfillCandidates"
COUNT_QUERY_TYPE = "EvaluationBackfillCount"

# Sampling resolution: cityHash64(key) % 10000 < rollout * 100 gives 0.01% steps, matching the
# rollout slider. The hash differs from the live scheduler's md5 on purpose, because the two paths
# never need to agree: dedupe removes any unit the live path already covered.
_SAMPLING_BUCKETS = 10000

_TARGET_TYPES: dict[str, str] = {
    EvaluationTarget.GENERATION.value: "generation_uuid",
    EvaluationTarget.TRACE.value: "trace_id",
    EvaluationTarget.SESSION.value: "session_id",
}

_UNITS_SQL = """
SELECT
    {unit_key} AS unit_id,
    min(timestamp) AS unit_timestamp,
    argMin(distinct_id, timestamp) AS distinct_id,
    argMin(properties.$session_id, timestamp) AS web_session_id,
    argMin(ai_events.trace_id, timestamp) AS unit_trace_id
FROM posthog.ai_events AS ai_events
WHERE event = '$ai_generation'
  AND isNotNull({unit_key})
  AND {unit_key} != ''
  AND timestamp >= {window_start}
  AND timestamp < {window_end}
  AND {condition_filter}
  AND {not_already_evaluated}
GROUP BY unit_id
"""

# Reads the shared events table rather than ai_events: the verdict rows must stay visible past the
# ai_events retention window, so a re-run of an old backfill still sees what it already covered.
_ALREADY_EVALUATED_SQL = """
SELECT properties.$ai_target_id
FROM events
WHERE event = '$ai_evaluation'
  AND properties.$ai_evaluation_id = {evaluation_id}
  AND {target_type_filter}
  AND timestamp >= {window_start}
  AND timestamp < {window_end} + INTERVAL 2 DAY
"""


@frozen
class BackfillCandidate:
    unit_id: str
    unit_timestamp: datetime
    distinct_id: str
    session_id: str | None
    trace_id: str | None


@frozen
class CandidatePage:
    candidates: list[BackfillCandidate]
    next_cursor_timestamp: datetime | None
    next_cursor_unit_id: str
    exhausted: bool


def _unit_key(target: str) -> ast.Expr:
    if target == EvaluationTarget.TRACE.value:
        return ast.Field(chain=["trace_id"])
    if target == EvaluationTarget.SESSION.value:
        return ast.Field(chain=["session_id"])
    if target == EvaluationTarget.GENERATION.value:
        # ai_events.uuid is a ClickHouse UUID, so it needs a String cast to compare against the
        # cursor and the dedupe subquery's target ids.
        return ast.Call(name="toString", args=[ast.Field(chain=["uuid"])])
    raise ValueError(f"Unsupported evaluation target: {target}")


def _target_type_filter(target: str) -> ast.Expr:
    target_type = ast.Field(chain=["properties", "$ai_target_type"])
    try:
        expected = _TARGET_TYPES[target]
    except KeyError:
        raise ValueError(f"Unsupported evaluation target: {target}") from None
    matches = ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=target_type, right=ast.Constant(value=expected))
    if target != EvaluationTarget.GENERATION.value:
        return matches
    # Verdicts emitted before $ai_target_type existed are generation verdicts, so a null value
    # belongs to the generation id space. Same rule as eval_reports/targets.py:target_event_predicate.
    return ast.Or(exprs=[matches, ast.Call(name="isNull", args=[target_type])])


def _sampling_predicate(unit_key: ast.Expr, rollout_percentage: float) -> ast.Expr | None:
    if rollout_percentage >= 100:
        return None
    return ast.CompareOperation(
        op=ast.CompareOperationOp.Lt,
        left=ast.ArithmeticOperation(
            op=ast.ArithmeticOperationOp.Mod,
            left=ast.Call(name="cityHash64", args=[unit_key]),
            right=ast.Constant(value=_SAMPLING_BUCKETS),
        ),
        right=ast.Constant(value=int(round(rollout_percentage * 100))),
    )


def build_condition_filter(conditions: list[dict[str, Any]], team: Team, unit_key: ast.Expr) -> ast.Expr | None:
    """OR across condition sets, AND within a set (properties AND sampling)."""
    sets: list[ast.Expr] = []
    for condition in conditions:
        parts: list[ast.Expr] = []
        props = condition.get("properties") or []
        if props:
            parts.append(property_to_expr(props, team))
        sampling = _sampling_predicate(unit_key, float(condition.get("rollout_percentage", 100)))
        if sampling is not None:
            parts.append(sampling)
        if len(parts) > 1:
            sets.append(ast.And(exprs=parts))
        else:
            sets.append(parts[0] if parts else ast.Constant(value=True))
    if not sets:
        return None
    return sets[0] if len(sets) == 1 else ast.Or(exprs=sets)


def _not_already_evaluated(
    *,
    unit_key: ast.Expr,
    evaluation_id: str,
    target: str,
    window_start: datetime,
    window_end: datetime,
) -> ast.Expr:
    # The upper bound keeps the subquery off the whole events history after the window. A live
    # verdict for a unit in the window lands within the longest settle budget, the 24 hour session
    # max age, plus ingestion lag, so two days covers every verdict this dedupe must see.
    already_evaluated = parse_select(
        _ALREADY_EVALUATED_SQL,
        placeholders={
            "evaluation_id": ast.Constant(value=evaluation_id),
            "target_type_filter": _target_type_filter(target),
            "window_start": ast.Constant(value=window_start),
            "window_end": ast.Constant(value=window_end),
        },
    )
    return ast.CompareOperation(op=ast.CompareOperationOp.NotIn, left=unit_key, right=already_evaluated)


def _units_query(
    *,
    team: Team,
    evaluation_id: str,
    target: str,
    conditions: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
    rerun_existing: bool,
) -> ast.SelectQuery:
    unit_key = _unit_key(target)
    condition_filter = build_condition_filter(conditions, team, unit_key)
    query = parse_select(
        _UNITS_SQL,
        placeholders={
            "unit_key": unit_key,
            "window_start": ast.Constant(value=window_start),
            "window_end": ast.Constant(value=window_end),
            "condition_filter": condition_filter if condition_filter is not None else ast.Constant(value=True),
            "not_already_evaluated": ast.Constant(value=True)
            if rerun_existing
            else _not_already_evaluated(
                unit_key=unit_key,
                evaluation_id=evaluation_id,
                target=target,
                window_start=window_start,
                window_end=window_end,
            ),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _cursor_predicate(cursor_timestamp: datetime, cursor_unit_id: str) -> ast.Expr:
    timestamp_field = ast.Field(chain=["unit_timestamp"])
    cursor = ast.Constant(value=cursor_timestamp)
    return ast.Or(
        exprs=[
            ast.CompareOperation(op=ast.CompareOperationOp.Lt, left=timestamp_field, right=cursor),
            ast.And(
                exprs=[
                    ast.CompareOperation(op=ast.CompareOperationOp.Eq, left=timestamp_field, right=cursor),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.Lt,
                        left=ast.Field(chain=["unit_id"]),
                        right=ast.Constant(value=cursor_unit_id),
                    ),
                ]
            ),
        ]
    )


def _run(query: ast.SelectQuery, *, team: Team, query_type: str) -> list[tuple[Any, ...]]:
    # Tagged here so both callers (the API estimate and the Temporal walk) attribute the same way.
    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.BACKFILL, team_id=team.pk):
        try:
            response = query_ai_events(
                query=query,
                placeholders={},
                team=team,
                query_type=query_type,
                fall_back_to_events=False,
                settings=HogQLGlobalSettings(max_execution_time=MAX_EXECUTION_TIME_SECONDS),
            )
        except (AIEventsNotFoundError, AIEventsExpiredError):
            return []
    return list(response.results or [])


def count_backfill_candidates(
    *,
    team: Team,
    evaluation_id: str,
    target: str,
    conditions: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
    rerun_existing: bool,
) -> int:
    units = _units_query(
        team=team,
        evaluation_id=evaluation_id,
        target=target,
        conditions=conditions,
        window_start=window_start,
        window_end=window_end,
        rerun_existing=rerun_existing,
    )
    query = ast.SelectQuery(
        select=[ast.Call(name="count", args=[])],
        select_from=ast.JoinExpr(table=units),
    )
    rows = _run(query, team=team, query_type=COUNT_QUERY_TYPE)
    return int(rows[0][0]) if rows else 0


def fetch_backfill_candidates(
    *,
    team: Team,
    evaluation_id: str,
    target: str,
    conditions: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
    rerun_existing: bool,
    cursor_timestamp: datetime | None,
    cursor_unit_id: str,
    limit: int,
) -> CandidatePage:
    query = _units_query(
        team=team,
        evaluation_id=evaluation_id,
        target=target,
        conditions=conditions,
        window_start=window_start,
        window_end=window_end,
        rerun_existing=rerun_existing,
    )
    if cursor_timestamp is not None:
        query.having = _cursor_predicate(cursor_timestamp, cursor_unit_id)
    query.order_by = [
        ast.OrderExpr(expr=ast.Field(chain=["unit_timestamp"]), order="DESC"),
        ast.OrderExpr(expr=ast.Field(chain=["unit_id"]), order="DESC"),
    ]
    query.limit = ast.Constant(value=limit)

    rows = _run(query, team=team, query_type=CANDIDATE_QUERY_TYPE)
    candidates = [
        BackfillCandidate(
            unit_id=str(row[0]),
            unit_timestamp=row[1],
            distinct_id=str(row[2]),
            session_id=str(row[3]) if row[3] else None,
            trace_id=str(row[4]) if row[4] else None,
        )
        for row in rows
    ]
    last = candidates[-1] if candidates else None
    return CandidatePage(
        candidates=candidates,
        next_cursor_timestamp=last.unit_timestamp if last else None,
        next_cursor_unit_id=last.unit_id if last else "",
        exhausted=len(rows) < limit,
    )
