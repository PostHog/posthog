from dataclasses import fields, replace
from datetime import UTC, datetime
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

from .trace_expressions import (
    EVENTS_COLUMNS,
    event_identified,
    event_is_otel,
    grouped,
    trace_cost,
    trace_errored,
    trace_latency,
    trace_person_id,
)
from .trace_metrics import BucketSize, PeriodTotals, bucket_starts
from .trace_selection import TraceSelection, TraceWindow, shift
from .trace_selection_queries import grouped_traces

METRICS_QUERY_NAME = "ai_trace_metrics"
_METRICS_QUERY_SECONDS = 30
_BUCKET_FUNCTIONS = {BucketSize.HOUR: "toStartOfHour", BucketSize.DAY: "toStartOfDay"}
_TOTALS_COLUMNS = frozenset(field.name for field in fields(PeriodTotals))
_NO_TRACES = PeriodTotals(
    traces=0,
    errored=0,
    cost=0.0,
    sessions=0,
    users=0,
    p95_latency_s=None,
    traces_with_cost=0,
    traces_with_latency=0,
    traces_with_session=0,
    identified_events=0,
    non_otel_generations=0,
)


@frozen
class TraceMetricsRows:
    current: PeriodTotals
    previous: PeriodTotals
    buckets: dict[datetime, PeriodTotals]


class TraceMetricsTooHeavyError(Exception):
    pass


def previous_window(window: TraceWindow) -> TraceWindow:
    length = window.end.astimezone(UTC) - window.start.astimezone(UTC)
    return TraceWindow(start=shift(window.start, -length), end=window.start)


def _per_trace_values(in_current: bool) -> dict[str, ast.Expr]:
    return {
        "in_current": ast.Constant(value=in_current),
        "trace_latency_s": trace_latency(EVENTS_COLUMNS, grouped),
        "trace_cost": trace_cost(EVENTS_COLUMNS, grouped),
        "has_error": trace_errored(EVENTS_COLUMNS, grouped),
        "session_id": parse_expr("any(properties.$ai_session_id)"),
        "trace_person_id": trace_person_id(EVENTS_COLUMNS, grouped),
        "trace_identified_events": ast.Call(name="countIf", args=[event_identified(EVENTS_COLUMNS)]),
        "trace_non_otel_generations": parse_expr(
            "countIf(event = '$ai_generation' AND NOT {otel})", placeholders={"otel": event_is_otel(EVENTS_COLUMNS)}
        ),
    }


def _period_traces(team: Team, selection: TraceSelection) -> ast.SelectQuery:
    # Each period reads its traces exactly as the list reads that range, so the current Traces and Errors equal the
    # list's counts. One read over both ranges would also see a current trace's events from before the current read
    # bounds, which the list never reads, and count that trace or its error where the list does not.
    # A trace in both reads keeps only its current row, so the periods never share a trace.
    previous = replace(selection, window=previous_window(selection.window))
    both_periods = ast.SelectSetQuery.create_from_queries(
        [
            grouped_traces(team, selection, _per_trace_values(in_current=True)),
            grouped_traces(team, previous, _per_trace_values(in_current=False)),
        ],
        "UNION ALL",
    )
    query = parse_select(
        "SELECT * FROM {both_periods} ORDER BY in_current DESC LIMIT 1 BY trace_id",
        placeholders={"both_periods": both_periods},
    )
    assert isinstance(query, ast.SelectQuery)
    return query


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
            uniqIf(session_id, isNotNull(session_id)) AS sessions,
            uniq(trace_person_id) AS users,
            quantile(0.95)(trace_latency_s) AS p95_latency_s,
            countIf(isNotNull(trace_cost)) AS traces_with_cost,
            countIf(isNotNull(trace_latency_s)) AS traces_with_latency,
            countIf(isNotNull(session_id)) AS traces_with_session,
            sum(trace_identified_events) AS identified_events,
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
    # ClickHouse floors buckets in the project's zone, and bucket_starts floors in the window's zone.
    zone = team.timezone_info
    window = TraceWindow(start=selection.window.start.astimezone(zone), end=selection.window.end.astimezone(zone))
    rows = _execute(team, user, _metrics_query(team, replace(selection, window=window), size))
    periods = {bool(row["in_current"]): _totals(row) for row in rows if row["is_period_total"]}
    return TraceMetricsRows(
        current=periods.get(True, _NO_TRACES),
        previous=periods.get(False, _NO_TRACES),
        buckets={row["bucket"]: _totals(row) for row in rows if row["in_current"] and not row["is_period_total"]},
    )
