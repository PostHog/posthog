"""One HogQL query shape serves both the pre-start estimate and the paged dispatch, so the number
a user approves and the units the workflow evaluates come from the same predicate.

Units are discovered on `events` rather than on `ai_events`. Both tables hold every AI event, but
their sort keys decide what a time range costs: `events` is ordered by `(team_id, toDate(timestamp),
event, ...)` and partitioned by month, so a team's `$ai_generation` rows over a range of days prune
to almost exactly the rows asked for, while `ai_events` is ordered by `(team_id, trace_id,
timestamp)`, where a range with no trace id prunes nothing and reads the team's whole history.

`ai_events` is still the only table carrying the heavy properties an evaluation can filter on, so a
condition set that reads one of those is settled by a second query against the trace ids the first
one found, which is a sort-key lookup rather than a scan.
"""

from datetime import datetime, timedelta
from typing import Any

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.clickhouse.workload import Workload
from posthog.dataclasses import frozen
from posthog.hogql_queries.ai.ai_table_resolver import AIEventsExpiredError, AIEventsNotFoundError, query_ai_events
from posthog.hogql_queries.ai.utils import HEAVY_PROPERTY_NAMES
from posthog.models.team import Team

from products.ai_observability.backend.evaluation_conditions import build_condition_filter
from products.ai_observability.backend.models.evaluations import EvaluationTarget

# The count runs inside an API request and the walk inside one activity attempt, so a filter that
# is too expensive for ClickHouse must fail the caller quickly rather than hold it for the 60s default.
MAX_EXECUTION_TIME_SECONDS = 30

# Room for the verdict event's own trip through ingestion, on top of the evaluation's settle
# horizon. A verdict that lands later than this is one the dedupe cannot see.
VERDICT_LAG_MARGIN = timedelta(days=1)

# How far below its cursor a page reads. A unit is ordered by its first event, so the query has to
# see that event to place it, but a unit's events sit in one burst: a generation is a single row and
# a trace or session closes within its settle horizon. Reading only that far below the cursor keeps
# every page the same width instead of growing back to the start of the window. A unit whose events
# outlast the lookback surfaces twice, once truncated and once at its true position, which costs
# nothing: both dispatches share a workflow id, so the second is a no-op counted as skipped.
MIN_SCAN_LOOKBACK = timedelta(days=1)

# A trace or session id is a plain event property, so capture takes one as large as the event it
# rides on, while a Temporal activity payload stops near 2 MiB. Bounding every id a candidate
# carries keeps a full batch far under that, and the bound sits in the query because the cursor is
# itself a unit id: a row skipped after the query would never be passed, stalling the walk on it.
MAX_CANDIDATE_ID_BYTES = 256

CANDIDATE_QUERY_TYPE = "EvaluationBackfillCandidates"
COUNT_QUERY_TYPE = "EvaluationBackfillCount"
HEAVY_MATCH_QUERY_TYPE = "EvaluationBackfillHeavyConditions"

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
    argMin(properties.$ai_trace_id, timestamp) AS unit_trace_id
FROM events
WHERE event = '$ai_generation'
  AND isNotNull({unit_key})
  AND {unit_key} != ''
  AND length({unit_key}) <= {max_id_bytes}
  AND timestamp >= {scan_start}
  AND timestamp < {window_end}
  AND {condition_filter}
  AND {not_already_evaluated}
GROUP BY unit_id
"""

# Settles the condition sets that read a heavy property, over the traces the units query already
# found. `trace_id` leads the ai_events sort key after the team, so this reads those traces rather
# than the window.
_HEAVY_MATCH_SQL = """
SELECT DISTINCT {unit_key} AS unit_id
FROM posthog.ai_events AS ai_events
WHERE event = '$ai_generation'
  AND {unit_scope}
  AND timestamp >= {scan_start}
  AND timestamp < {window_end}
  AND {condition_filter}
"""

# Counting a heavy filter means asking ai_events directly, because the traces to ask about are
# exactly what is being counted. It stays one aggregate: listing the window's units in Python to
# refine them afterwards would let one estimate request hold a whole window in memory.
_AI_UNITS_SQL = """
SELECT {unit_key} AS unit_id
FROM posthog.ai_events AS ai_events
WHERE event = '$ai_generation'
  AND isNotNull({unit_key})
  AND {unit_key} != ''
  AND length({unit_key}) <= {max_id_bytes}
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
  AND timestamp < {verdict_end}
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
    """The unit id as `events` carries it. Only the generation uuid is a column there."""
    if target == EvaluationTarget.TRACE.value:
        return ast.Field(chain=["properties", "$ai_trace_id"])
    if target == EvaluationTarget.SESSION.value:
        return ast.Field(chain=["properties", "$ai_session_id"])
    if target == EvaluationTarget.GENERATION.value:
        # A ClickHouse UUID needs a String cast to compare against the cursor and against the
        # dedupe subquery's target ids.
        return ast.Call(name="toString", args=[ast.Field(chain=["uuid"])])
    raise ValueError(f"Unsupported evaluation target: {target}")


def _ai_events_unit_key(target: str) -> ast.Expr:
    """The same unit id as `ai_events` carries it, where trace and session are native columns."""
    if target == EvaluationTarget.TRACE.value:
        return ast.Field(chain=["trace_id"])
    if target == EvaluationTarget.SESSION.value:
        return ast.Field(chain=["session_id"])
    if target == EvaluationTarget.GENERATION.value:
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


def reads_heavy_properties(conditions: list[dict[str, Any]]) -> bool:
    """Whether any condition set filters on a property `events` does not carry."""
    return any(
        str(prop.get("key")) in HEAVY_PROPERTY_NAMES
        for condition in conditions
        for prop in (condition.get("properties") or [])
    )


def _without_heavy_properties(conditions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same condition sets with the heavy filters dropped, so they match a superset.

    What survives runs on `events` to find the units worth asking about; the full sets then settle
    which of those actually match.
    """
    return [
        {
            **condition,
            "properties": [
                prop for prop in (condition.get("properties") or []) if str(prop.get("key")) not in HEAVY_PROPERTY_NAMES
            ],
        }
        for condition in conditions
    ]


def _not_already_evaluated(
    *,
    unit_key: ast.Expr,
    evaluation_id: str,
    target: str,
    window_start: datetime,
    window_end: datetime,
    settle_horizon: timedelta,
) -> ast.Expr:
    # The upper bound keeps the subquery off the whole events history after the window. A live
    # verdict is stamped when its unit finishes settling, so it can trail the unit by the whole
    # settle horizon the evaluation is configured with, up to 7 days for a session. Reading that
    # number from the evaluation rather than assuming one keeps the scan tight where the wait is
    # short, which is every generation and every trace.
    already_evaluated = parse_select(
        _ALREADY_EVALUATED_SQL,
        placeholders={
            "evaluation_id": ast.Constant(value=evaluation_id),
            "target_type_filter": _target_type_filter(target),
            "window_start": ast.Constant(value=window_start),
            "verdict_end": ast.Constant(value=window_end + settle_horizon + VERDICT_LAG_MARGIN),
        },
    )
    return ast.CompareOperation(op=ast.CompareOperationOp.NotIn, left=unit_key, right=already_evaluated)


def _units_query(
    *,
    team: Team,
    evaluation_id: str,
    target: str,
    settle_horizon: timedelta,
    conditions: list[dict[str, Any]],
    scan_start: datetime,
    window_start: datetime,
    window_end: datetime,
    rerun_existing: bool,
) -> ast.SelectQuery:
    """Units in `[scan_start, window_end)` that the evaluation has not judged yet."""
    unit_key = _unit_key(target)
    condition_filter = build_condition_filter(_without_heavy_properties(conditions), team, unit_key)
    query = parse_select(
        _UNITS_SQL,
        placeholders={
            "unit_key": unit_key,
            "max_id_bytes": ast.Constant(value=MAX_CANDIDATE_ID_BYTES),
            "scan_start": ast.Constant(value=scan_start),
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
                settle_horizon=settle_horizon,
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


def _bounded_id(value: Any) -> str | None:
    """An id a candidate carries alongside its unit, dropped when it is too large to ship.

    Both are optional to the run that receives them: one narrows the child's ClickHouse scan and
    the other becomes a property on the verdict, so losing an absurd one beats failing the tick.
    """
    if not value:
        return None
    text = str(value)
    return text if len(text.encode()) <= MAX_CANDIDATE_ID_BYTES else None


def _scan_start(*, window_start: datetime, cursor_timestamp: datetime | None, settle_horizon: timedelta) -> datetime:
    if cursor_timestamp is None:
        return window_start
    return max(window_start, cursor_timestamp - max(settle_horizon, MIN_SCAN_LOOKBACK))


def _run(query: ast.SelectQuery, *, team: Team, query_type: str) -> list[tuple[Any, ...]]:
    # Tagged here so both callers (the API estimate and the Temporal walk) attribute the same way.
    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.BACKFILL, team_id=team.pk):
        response = execute_hogql_query(
            query=query,
            team=team,
            query_type=query_type,
            workload=Workload.OFFLINE,
            settings=HogQLGlobalSettings(max_execution_time=MAX_EXECUTION_TIME_SECONDS),
        )
    return list(response.results or [])


def _run_on_ai_events(
    query: ast.SelectQuery, placeholders: dict[str, ast.Expr], *, team: Team, query_type: str
) -> list[tuple[Any, ...]]:
    """Runs through the ai_events resolver, which rewrites a heavy property read onto its column.

    Only what arrives in `placeholders` is rewritten, so a condition filter baked into the parsed
    query would read a `properties.$ai_input` that ai_events does not carry, and match nothing.
    """
    with tags_context(product=Product.LLM_ANALYTICS, feature=Feature.BACKFILL, team_id=team.pk):
        try:
            response = query_ai_events(
                query=query,
                placeholders=placeholders,
                team=team,
                query_type=query_type,
                fall_back_to_events=False,
                workload=Workload.OFFLINE,
                settings=HogQLGlobalSettings(max_execution_time=MAX_EXECUTION_TIME_SECONDS),
            )
        except (AIEventsNotFoundError, AIEventsExpiredError):
            return []
    return list(response.results or [])


def _heavy_matches(
    *,
    team: Team,
    target: str,
    conditions: list[dict[str, Any]],
    candidates: list[BackfillCandidate],
    scan_start: datetime,
    window_end: datetime,
) -> set[str]:
    """Which of these candidates match the condition sets in full, heavy filters included."""
    if not candidates:
        return set()
    unit_key = _ai_events_unit_key(target)
    trace_ids = sorted({candidate.trace_id for candidate in candidates if candidate.trace_id})
    scope: ast.Expr = ast.CompareOperation(
        op=ast.CompareOperationOp.In,
        left=ast.Field(chain=["trace_id"]),
        right=ast.Constant(value=trace_ids),
    )
    # A generation can carry a heavy property and no trace id at all, and for a generation or
    # session unit that is still a candidate. Reaching it by its own id keeps it judged rather
    # than dropped, and the clause is only added when such a candidate is on the page, so the
    # ordinary lookup keeps reading by the sort key alone.
    untraced = sorted({candidate.unit_id for candidate in candidates if not candidate.trace_id})
    if untraced:
        scope = ast.Or(
            exprs=[
                scope,
                ast.CompareOperation(op=ast.CompareOperationOp.In, left=unit_key, right=ast.Constant(value=untraced)),
            ]
        )
    condition_filter = build_condition_filter(conditions, team, unit_key)
    query = parse_select(_HEAVY_MATCH_SQL)
    assert isinstance(query, ast.SelectQuery)
    rows = _run_on_ai_events(
        query,
        {
            "unit_key": unit_key,
            "unit_scope": scope,
            "scan_start": ast.Constant(value=scan_start),
            "window_end": ast.Constant(value=window_end),
            "condition_filter": condition_filter if condition_filter is not None else ast.Constant(value=True),
        },
        team=team,
        query_type=HEAVY_MATCH_QUERY_TYPE,
    )
    return {str(row[0]) for row in rows}


def count_backfill_candidates(
    *,
    team: Team,
    evaluation_id: str,
    target: str,
    settle_horizon: timedelta,
    conditions: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
    rerun_existing: bool,
) -> int:
    units = _units_query(
        team=team,
        evaluation_id=evaluation_id,
        target=target,
        settle_horizon=settle_horizon,
        conditions=conditions,
        scan_start=window_start,
        window_start=window_start,
        window_end=window_end,
        rerun_existing=rerun_existing,
    )
    if not reads_heavy_properties(conditions):
        query = ast.SelectQuery(select=[ast.Call(name="count", args=[])], select_from=ast.JoinExpr(table=units))
        rows = _run(query, team=team, query_type=COUNT_QUERY_TYPE)
        return int(rows[0][0]) if rows else 0

    # `events` cannot judge a heavy filter, and the traces to ask ai_events about are exactly what
    # is being counted, so the count asks ai_events for all of it and comes back with one number.
    # The scan is the wide one this module otherwise avoids, which is the price of counting a
    # filter on a property only that table holds, and the execution cap bounds it.
    ai_unit_key = _ai_events_unit_key(target)
    ai_units = parse_select(_AI_UNITS_SQL)
    assert isinstance(ai_units, ast.SelectQuery)
    rows = _run_on_ai_events(
        ast.SelectQuery(select=[ast.Call(name="count", args=[])], select_from=ast.JoinExpr(table=ai_units)),
        {
            "unit_key": ai_unit_key,
            "max_id_bytes": ast.Constant(value=MAX_CANDIDATE_ID_BYTES),
            "window_start": ast.Constant(value=window_start),
            "window_end": ast.Constant(value=window_end),
            "condition_filter": build_condition_filter(conditions, team, ai_unit_key) or ast.Constant(value=True),
            "not_already_evaluated": ast.Constant(value=True)
            if rerun_existing
            else _not_already_evaluated(
                unit_key=ai_unit_key,
                evaluation_id=evaluation_id,
                target=target,
                window_start=window_start,
                window_end=window_end,
                settle_horizon=settle_horizon,
            ),
        },
        team=team,
        query_type=COUNT_QUERY_TYPE,
    )
    return int(rows[0][0]) if rows else 0


def fetch_backfill_candidates(
    *,
    team: Team,
    evaluation_id: str,
    target: str,
    settle_horizon: timedelta,
    conditions: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
    rerun_existing: bool,
    cursor_timestamp: datetime | None,
    cursor_unit_id: str,
    limit: int,
) -> CandidatePage:
    scan_start = _scan_start(
        window_start=window_start, cursor_timestamp=cursor_timestamp, settle_horizon=settle_horizon
    )
    query = _units_query(
        team=team,
        evaluation_id=evaluation_id,
        target=target,
        settle_horizon=settle_horizon,
        conditions=conditions,
        scan_start=scan_start,
        window_start=window_start,
        window_end=window_end,
        rerun_existing=rerun_existing,
    )
    if cursor_timestamp is not None:
        query.having = _cursor_predicate(cursor_timestamp, cursor_unit_id)
        # A unit whose first generation is after the cursor is already excluded by HAVING, and
        # every remaining unit keeps the same min(timestamp) once later rows are dropped. So this
        # bound changes no result, it only stops ClickHouse from reading rows the walk has passed.
        cursor_bound = ast.CompareOperation(
            op=ast.CompareOperationOp.LtEq,
            left=ast.Field(chain=["timestamp"]),
            right=ast.Constant(value=cursor_timestamp),
        )
        query.where = ast.And(exprs=[query.where, cursor_bound]) if query.where is not None else cursor_bound
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
            session_id=_bounded_id(row[3]),
            trace_id=_bounded_id(row[4]),
        )
        for row in rows
    ]
    # The cursor tracks what the page examined, not what survived, so a unit the heavy filter
    # rejects is passed over once rather than met again on the next tick.
    examined = candidates[-1] if candidates else None
    if reads_heavy_properties(conditions):
        matched = _heavy_matches(
            team=team,
            target=target,
            conditions=conditions,
            candidates=candidates,
            scan_start=scan_start,
            window_end=window_end,
        )
        candidates = [candidate for candidate in candidates if candidate.unit_id in matched]

    if len(rows) == limit and examined is not None:
        return CandidatePage(
            candidates=candidates,
            next_cursor_timestamp=examined.unit_timestamp,
            next_cursor_unit_id=examined.unit_id,
            exhausted=False,
        )
    # A short page means this slice is spent, not the window: the walk drops to the slice's own
    # floor and carries on until that floor is the start of the window.
    if scan_start > window_start:
        return CandidatePage(
            candidates=candidates,
            next_cursor_timestamp=scan_start,
            next_cursor_unit_id="",
            exhausted=False,
        )
    return CandidatePage(
        candidates=candidates,
        next_cursor_timestamp=examined.unit_timestamp if examined else None,
        next_cursor_unit_id=examined.unit_id if examined else "",
        exhausted=True,
    )
