from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.context import HogQLContext
from posthog.hogql.database.database import Database
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.printer.utils import to_printed_hogql
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.visitor import CloningVisitor

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

from products.ai_observability.backend.logic.instrumentation.signal_queries import (
    event_declines_session,
    identified_generation_person,
    sdk_generation_identified,
)

from .trace_expression_queries import (
    EVENTS_COLUMNS,
    event_is_otel,
    grouped,
    trace_cost,
    trace_errored,
    trace_latency,
    trace_session_id,
)
from .trace_metrics import NO_TRACES, BucketSize, MetricKey, PeriodTotals, bucket_starts, previous_window
from .trace_selection import TraceSelection, TraceWindow, shift
from .trace_selection_queries import grouped_traces, selection_database

METRICS_QUERY_NAME = "ai_trace_metrics"
_METRICS_QUERY_SECONDS = 30
_BUCKET_FUNCTIONS = {BucketSize.HOUR: "toStartOfHour", BucketSize.DAY: "toStartOfDay"}
_BUCKET_STEPS = {BucketSize.HOUR: "INTERVAL 1 HOUR", BucketSize.DAY: "INTERVAL 1 DAY"}
# Aggregates over one row per trace. The tile read and each tile's insight query both use them, so the two agree.
_TOTALS = {
    "traces": "count()",
    "errored": "countIf(has_error)",
    "cost": "sum(ifNull(trace_cost, 0))",
    "sessions": "uniqIf(trace_session_id, isNotNull(trace_session_id))",
    "users": "uniqIf(trace_user_id, isNotNull(trace_user_id))",
    "p50_latency_s": "quantile(0.5)(trace_latency_s)",
    "p95_latency_s": "quantile(0.95)(trace_latency_s)",
    "p99_latency_s": "quantile(0.99)(trace_latency_s)",
    "traces_with_cost": "countIf(isNotNull(trace_cost))",
    "traces_with_latency": "countIf(isNotNull(trace_latency_s))",
    "traces_with_session": "countIf(isNotNull(trace_session_id))",
    "session_declines": "sum(trace_session_declines)",
    "identified_generations": "sum(trace_identified_generations)",
    "non_otel_generations": "sum(trace_non_otel_generations)",
}
_SERIES = {
    MetricKey.COST: _TOTALS["cost"],
    MetricKey.USERS: _TOTALS["users"],
    MetricKey.SESSIONS: _TOTALS["sessions"],
    MetricKey.TRACES: _TOTALS["traces"],
    # Nullable, so a bucket the fill adds has no error rate, as on the tile, rather than a rate of zero.
    MetricKey.ERROR_RATE: f"{_TOTALS['errored']} / nullIf({_TOTALS['traces']}, 0)",
    MetricKey.P95_LATENCY: _TOTALS["p95_latency_s"],
}


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
        "trace_user_id": identified_generation_person(EVENTS_COLUMNS, grouped),
        "trace_identified_generations": ast.Call(name="countIf", args=[sdk_generation_identified(EVENTS_COLUMNS)]),
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


def _last_moment(window: TraceWindow) -> ast.Constant:
    return ast.Constant(value=shift(window.end, -timedelta(microseconds=1)))


def _bucket(size: BucketSize, period_start: ast.Expr, period_last_moment: ast.Expr) -> ast.Expr:
    # A trace starting before its period lands in the period's first bucket, which bucket_starts floors the same way.
    # The period includes its end, and bucket_starts has no bucket starting there, so a trace starting exactly at the
    # end lands in the last bucket.
    return ast.Call(
        name=_BUCKET_FUNCTIONS[size],
        args=[
            parse_expr(
                "least(greatest(first_timestamp, {start}), {last_moment})",
                placeholders={"start": period_start, "last_moment": period_last_moment},
            )
        ],
    )


def _metrics_query(team: Team, selection: TraceSelection, size: BucketSize) -> ast.SelectQuery:
    current = selection.window
    previous = previous_window(current)
    period_start = parse_expr(
        "if(in_current, {current_start}, {previous_start})",
        placeholders={
            "current_start": ast.Constant(value=current.start),
            "previous_start": ast.Constant(value=previous.start),
        },
    )
    period_last_moment = parse_expr(
        "if(in_current, {current_last}, {previous_last})",
        placeholders={"current_last": _last_moment(current), "previous_last": _last_moment(previous)},
    )
    # Each period yields one row per bucket and one total row, the one `grouping(bucket)` marks. p95, sessions and
    # users do not add up across buckets, so the totals come from that row.
    most_rows = len(bucket_starts(previous, size)) + len(bucket_starts(current, size)) + 2
    # Totals sort first, so the LIMIT can only ever cut a bucket row.
    query = parse_select(
        """
        SELECT in_current, {bucket} AS bucket, grouping(bucket) AS is_period_total
        FROM {traces}
        GROUP BY GROUPING SETS ((in_current), (in_current, bucket))
        ORDER BY is_period_total DESC
        LIMIT {most_rows}
        """,
        placeholders={
            "bucket": _bucket(size, period_start, period_last_moment),
            "most_rows": ast.Constant(value=most_rows),
            "traces": _period_traces(team, selection),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    query.select.extend(ast.Alias(alias=name, expr=parse_expr(aggregate)) for name, aggregate in _TOTALS.items())
    return query


def _series_query(team: Team, selection: TraceSelection, size: BucketSize, key: MetricKey) -> ast.SelectQuery:
    """The tile's series from the current period's read alone, since the tile read keeps a current trace's row from
    that read. Buckets with no trace are filled in, as the tile's series has them."""
    window = selection.window
    floor = _BUCKET_FUNCTIONS[size]
    # The fill bounds go through the bucket function, so they have the bucket's type, which WITH FILL requires. The
    # end bound may add a bucket past the window, and the LIMIT drops it.
    query = parse_select(
        """
        SELECT {bucket} AS bucket, {value} AS value
        FROM {traces}
        GROUP BY bucket
        ORDER BY bucket WITH FILL FROM {first_bucket} TO {last_bucket} + {step} STEP {step}
        LIMIT {buckets}
        """,
        placeholders={
            "bucket": _bucket(size, ast.Constant(value=window.start), _last_moment(window)),
            "value": parse_expr(_SERIES[key]),
            "traces": grouped_traces(team, selection, _per_trace_values()),
            "first_bucket": ast.Call(name=floor, args=[ast.Constant(value=window.start)]),
            "last_bucket": ast.Call(name=floor, args=[ast.Constant(value=window.end)]),
            "step": parse_expr(_BUCKET_STEPS[size]),
            "buckets": ast.Constant(value=len(bucket_starts(window, size))),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


class _OverriddenPropertyTypes(CloningVisitor):
    # The tile read types these properties as strings through its query context, which printed HogQL does not carry.
    # A property read would take the team's type for them, and a number type turns a non-numeric id into NULL before
    # any cast. Reading the stored text from the JSON is what the property swapper leaves alone.
    def visit_field(self, node: ast.Field) -> ast.Expr:
        match node.chain:
            case ["properties", str(name)] if EVENTS_FALLBACK_PROPERTY_TYPE_OVERRIDES.get(name) == "String":
                return parse_expr(
                    "replaceRegexpAll(nullIf(nullIf(JSONExtractRaw(properties, {name}), ''), 'null'), '^\"|\"$', '')",
                    placeholders={"name": ast.Constant(value=name)},
                )
        return super().visit_field(node)


def metrics_insight_queries(team: Team, selection: TraceSelection, size: BucketSize) -> dict[MetricKey, str]:
    """Each tile's series as HogQL to run as an SQL insight. Reads the team's schema from Postgres but runs no
    ClickHouse query."""
    database = selection_database(team, selection) or Database.create_for(team=team)
    return {
        key: to_printed_hogql(
            _OverriddenPropertyTypes().visit(_series_query(team, selection, size, key)), team, database=database
        )
        for key in MetricKey
    }


def _execute(team: Team, user: User | None, selection: TraceSelection, query: ast.SelectQuery) -> list[dict[str, Any]]:
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
                    team_id=team.pk,
                    user=user,
                    database=selection_database(team, selection),
                    property_type_overrides=EVENTS_FALLBACK_PROPERTY_TYPE_OVERRIDES,
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
    return PeriodTotals(**{column: row[column] for column in _TOTALS})


def load_trace_metrics(team: Team, user: User | None, selection: TraceSelection, size: BucketSize) -> TraceMetricsRows:
    """ClickHouse floors buckets in the project's zone, so the selection's window must be in that zone too for
    `bucket_starts` to match them. The buckets are keyed by their start in UTC."""
    rows = _execute(team, user, selection, _metrics_query(team, selection, size))
    periods = {bool(row["in_current"]): _totals(row) for row in rows if row["is_period_total"]}
    return TraceMetricsRows(
        current=periods.get(True, NO_TRACES),
        previous=periods.get(False, NO_TRACES),
        # In the project's zone, the two buckets of the hour a clock goes back would collapse into one key.
        buckets={
            row["bucket"].astimezone(UTC): _totals(row)
            for row in rows
            if row["in_current"] and not row["is_period_total"]
        },
    )
