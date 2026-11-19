from dataclasses import fields, replace
from datetime import datetime
from typing import Any

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Product, tag_queries, tags_context
from posthog.dataclasses import frozen
from posthog.errors import (
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.hogql_queries.ai.ai_column_rewriter import EVENTS_FALLBACK_PROPERTY_TYPE_OVERRIDES
from posthog.models import Team, User

from .trace_expression_queries import (
    EVENTS_COLUMNS,
    event_declines_session,
    event_is_otel,
    generation_identified,
    grouped,
    trace_cost,
    trace_errored,
    trace_latency,
    trace_person_id,
    trace_session_id,
)
from .trace_metrics import NO_TRACES, BucketSize, PeriodTotals, bucket_starts, previous_window
from .trace_selection import TraceSelection
from .trace_selection_queries import grouped_traces

METRICS_QUERY_NAME = "ai_trace_metrics"
_METRICS_QUERY_SECONDS = 30
_BUCKET_FUNCTIONS = {BucketSize.HOUR: "toStartOfHour", BucketSize.DAY: "toStartOfDay"}
_TOTALS_COLUMNS = frozenset(field.name for field in fields(PeriodTotals))


@frozen
class TraceMetricsRows:
    current: PeriodTotals
    previous: PeriodTotals
    buckets: dict[datetime, PeriodTotals]


class TraceMetricsTooHeavyError(Exception):
    pass


def _per_trace_values() -> dict[str, ast.Expr]:
    return {
        "trace_latency_s": trace_latency(EVENTS_COLUMNS, grouped),
        "trace_cost": trace_cost(EVENTS_COLUMNS, grouped),
        "has_error": trace_errored(EVENTS_COLUMNS, grouped),
        "trace_session_id": trace_session_id(EVENTS_COLUMNS, grouped),
        "trace_session_declines": ast.Call(name="countIf", args=[event_declines_session(EVENTS_COLUMNS)]),
        "trace_person_id": trace_person_id(EVENTS_COLUMNS, grouped),
        "trace_identified_generations": ast.Call(name="countIf", args=[generation_identified(EVENTS_COLUMNS)]),
        "trace_non_otel_generations": parse_expr(
            "countIf(event = '$ai_generation' AND NOT {otel})", placeholders={"otel": event_is_otel(EVENTS_COLUMNS)}
        ),
    }


def _period_read(team: Team, selection: TraceSelection, *, current: bool) -> ast.SelectQuery:
    return grouped_traces(team, selection, {"current_read": ast.Constant(value=current), **_per_trace_values()})


def _period_traces(team: Team, selection: TraceSelection) -> ast.SelectQuery:
    # Each period reads its traces exactly as the list reads that range, so the current Traces and Errors equal the
    # list's counts. One read over both ranges would also see a current trace's events from before the current read
    # bounds, which the list never reads, and count that trace or its error where the list does not.
    # A trace in both reads keeps only its current row, so the periods never share a trace.
    previous = replace(selection, window=previous_window(selection.window))
    both_periods = ast.SelectSetQuery.create_from_queries(
        [_period_read(team, selection, current=True), _period_read(team, previous, current=False)],
        "UNION ALL",
    )
    # Grouping by trace keeps the current row without sorting every trace. argMax skips a NULL value, so each value is
    # wrapped in a tuple, or a NULL in the current row would hand over the previous row's value.
    return ast.SelectQuery(
        select=[
            ast.Field(chain=["trace_id"]),
            ast.Alias(alias="in_current", expr=parse_expr("max(current_read)")),
            *(
                ast.Alias(
                    alias=name,
                    expr=parse_expr(
                        "tupleElement(argMax(tuple({value}), current_read), 1)",
                        placeholders={"value": ast.Field(chain=[name])},
                    ),
                )
                for name in ("first_timestamp", *_per_trace_values())
            ),
        ],
        select_from=ast.JoinExpr(table=both_periods),
        group_by=[ast.Field(chain=["trace_id"])],
    )


def _metrics_query(team: Team, selection: TraceSelection, size: BucketSize) -> ast.SelectQuery | ast.SelectSetQuery:
    current = selection.window
    previous = previous_window(current)
    current_start, previous_start = ast.Constant(value=current.start), ast.Constant(value=previous.start)
    # A trace starting before its period lands in the period's first bucket, which bucket_starts floors the same way.
    bucket = ast.Call(
        name=_BUCKET_FUNCTIONS[size],
        args=[
            parse_expr(
                "greatest(first_timestamp, if(in_current, {current_start}, {previous_start}))",
                placeholders={"current_start": current_start, "previous_start": previous_start},
            )
        ],
    )
    # Each period yields one row per bucket and one total row, the one `grouping(bucket)` marks. p95, sessions and
    # users do not add up across buckets, so the totals come from that row.
    most_rows = len(bucket_starts(previous, size)) + len(bucket_starts(current, size)) + 2
    # Totals sort first, so the LIMIT can only ever cut a bucket row.
    return parse_select(
        """
        SELECT
            in_current,
            {bucket} AS bucket,
            grouping(bucket) AS is_period_total,
            count() AS traces,
            countIf(has_error) AS errored,
            sum(ifNull(trace_cost, 0)) AS cost,
            uniqIf(trace_session_id, isNotNull(trace_session_id)) AS sessions,
            uniqIf(trace_person_id, trace_identified_generations > 0) AS users,
            quantile(0.95)(trace_latency_s) AS p95_latency_s,
            countIf(isNotNull(trace_cost)) AS traces_with_cost,
            countIf(isNotNull(trace_latency_s)) AS traces_with_latency,
            countIf(isNotNull(trace_session_id)) AS traces_with_session,
            sum(trace_session_declines) AS session_declines,
            sum(trace_identified_generations) AS identified_generations,
            sum(trace_non_otel_generations) AS non_otel_generations
        FROM {traces}
        GROUP BY GROUPING SETS ((in_current), (in_current, bucket))
        ORDER BY is_period_total DESC
        LIMIT {most_rows}
        """,
        placeholders={
            "bucket": bucket,
            "most_rows": ast.Constant(value=most_rows),
            "traces": _period_traces(team, selection),
        },
    )


def _execute(team: Team, user: User | None, query: ast.SelectQuery | ast.SelectSetQuery) -> list[dict[str, Any]]:
    try:
        with tags_context(product=Product.LLM_ANALYTICS):
            tag_queries(name=METRICS_QUERY_NAME)
            response = execute_hogql_query(
                query=query,
                team=team,
                user=user,
                query_type=METRICS_QUERY_NAME,
                workload=Workload.ONLINE,
                context=HogQLContext(
                    team_id=team.pk, user=user, property_type_overrides=EVENTS_FALLBACK_PROPERTY_TYPE_OVERRIDES
                ),
                settings=HogQLGlobalSettings(max_execution_time=_METRICS_QUERY_SECONDS, timeout_overflow_mode="throw"),
            )
    except (ClickHouseQueryTimeOut, ClickHouseEstimatedQueryExecutionTimeTooLong) as error:
        raise TraceMetricsTooHeavyError() from error
    except ClickHouseQueryMemoryLimitExceeded as error:
        if error.is_per_query_limit:
            raise TraceMetricsTooHeavyError() from error
        raise
    return [dict(zip(response.columns or [], row)) for row in response.results]


def _totals(row: dict[str, Any]) -> PeriodTotals:
    return PeriodTotals(**{column: value for column, value in row.items() if column in _TOTALS_COLUMNS})


def load_trace_metrics(team: Team, user: User | None, selection: TraceSelection, size: BucketSize) -> TraceMetricsRows:
    """Bucket starts come back in the project's zone, which ClickHouse floors in, so the selection's window must be in
    that zone too for `bucket_starts` to match them."""
    rows = _execute(team, user, _metrics_query(team, selection, size))
    periods = {bool(row["in_current"]): _totals(row) for row in rows if row["is_period_total"]}
    return TraceMetricsRows(
        current=periods.get(True, NO_TRACES),
        previous=periods.get(False, NO_TRACES),
        buckets={row["bucket"]: _totals(row) for row in rows if row["in_current"] and not row["is_period_total"]},
    )
