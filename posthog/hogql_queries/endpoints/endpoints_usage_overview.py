from posthog.schema import (
    CachedEndpointsUsageOverviewQueryResponse,
    EndpointsUsageOverviewItem,
    EndpointsUsageOverviewQuery,
    EndpointsUsageOverviewQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.endpoints.endpoints_usage_query_runner import EndpointsUsageQueryRunner
from posthog.hogql_queries.utils.query_previous_period_date_range import QueryPreviousPeriodDateRange
from posthog.models.filters.mixins.utils import cached_property


class EndpointsUsageOverviewQueryRunner(EndpointsUsageQueryRunner[EndpointsUsageOverviewQueryResponse]):
    """Returns summary metrics for endpoint usage.

    Metrics returned:
    - total_requests: Total number of endpoint executions
    - total_bytes_read: Sum of bytes read from storage
    - total_cpu_seconds: Sum of CPU time consumed
    - avg_query_duration_ms: Average query duration
    - p95_query_duration_ms: 95th percentile query duration
    - error_rate: Percentage of failed executions
    - materialized_requests: Count of materialized endpoint executions
    - inline_requests: Count of non-materialized (direct) endpoint executions
    """

    query: EndpointsUsageOverviewQuery
    cached_response: CachedEndpointsUsageOverviewQueryResponse

    @cached_property
    def query_previous_date_range(self) -> QueryPreviousPeriodDateRange | None:
        if not self.query.compareFilter or not self.query.compareFilter.compare:
            return None

        from datetime import datetime

        return QueryPreviousPeriodDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=None,
            now=datetime.now(),
        )

    def to_query(self) -> ast.SelectQuery:
        return self._build_query(is_previous=False)

    def _build_query(self, is_previous: bool = False) -> ast.SelectQuery:
        """Build the overview query for current or previous period."""
        # Determine date range based on whether this is previous period
        if is_previous and self.query_previous_date_range:
            date_from = self.query_previous_date_range.date_from()
            date_to = self.query_previous_date_range.date_to()
        else:
            date_from = self.query_date_range.date_from()
            date_to = self.query_date_range.date_to()

        # Build WHERE conditions
        conditions = self._get_base_where_conditions()

        # Override date conditions for this specific period
        # Remove existing date conditions and add new ones
        conditions = [c for c in conditions if not self._is_date_condition(c)]

        if date_from:
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["event_date"]),
                    right=ast.Constant(value=date_from),
                )
            )
        if date_to:
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["event_date"]),
                    right=ast.Constant(value=date_to),
                )
            )

        where_clause = ast.And(exprs=conditions) if len(conditions) > 1 else conditions[0] if conditions else None

        return ast.SelectQuery(
            select=[
                ast.Alias(alias="total_requests", expr=self._get_requests_count_expression()),
                ast.Alias(alias="total_bytes_read", expr=self._get_bytes_read_expression()),
                ast.Alias(alias="total_cpu_seconds", expr=self._get_cpu_seconds_expression()),
                ast.Alias(alias="avg_query_duration_ms", expr=self._get_avg_latency_expression()),
                ast.Alias(alias="p95_query_duration_ms", expr=self._get_p95_latency_expression()),
                ast.Alias(alias="error_rate", expr=self._get_error_rate_expression()),
                ast.Alias(alias="materialized_requests", expr=self._get_materialized_count_expression()),
                ast.Alias(alias="inline_requests", expr=self._get_inline_count_expression()),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["query_log"])),
            where=where_clause,
        )

    def _is_date_condition(self, condition: ast.Expr) -> bool:
        """Check if a condition is a date-related condition."""
        if isinstance(condition, ast.CompareOperation):
            if isinstance(condition.left, ast.Field):
                return condition.left.chain == ["event_date"]
        return False

    def _calculate(self) -> EndpointsUsageOverviewQueryResponse:
        from posthog.clickhouse.query_tagging import tag_queries

        # Execute current period query
        tag_queries(name="endpoints_usage_overview")
        response = execute_hogql_query(
            query_type="endpoints_usage_overview_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        # Execute previous period query if comparison is enabled
        previous_values: dict[str, float] | None = None
        if self.query_previous_date_range:
            tag_queries(name="endpoints_usage_overview_previous")
            previous_response = execute_hogql_query(
                query_type="endpoints_usage_overview_query_previous",
                query=self._build_query(is_previous=True),
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )
            if previous_response.results and len(previous_response.results) > 0:
                prev_row = previous_response.results[0]
                previous_values = self._row_to_metrics_dict(prev_row)

        # Build results
        results: list[EndpointsUsageOverviewItem] = []

        if response.results and len(response.results) > 0:
            row = response.results[0]
            current_metrics = self._row_to_metrics_dict(row)

            for key, value in current_metrics.items():
                item = EndpointsUsageOverviewItem(
                    key=key,
                    value=value,
                )

                if previous_values:
                    prev_value = previous_values.get(key, 0.0)
                    item.previous = prev_value
                    item.changeFromPreviousPct = self._calculate_change_pct(value, prev_value)

                results.append(item)

        return EndpointsUsageOverviewQueryResponse(
            results=results,
            timings=response.timings,
            hogql=response.hogql,
        )

    def _row_to_metrics_dict(self, row: list) -> dict[str, float]:
        """Convert a query result row to a metrics dictionary."""
        from posthog.hogql_queries.endpoints.endpoints_usage_query_runner import safe_float

        metric_keys = [
            "total_requests",
            "total_bytes_read",
            "total_cpu_seconds",
            "avg_query_duration_ms",
            "p95_query_duration_ms",
            "error_rate",
            "materialized_requests",
            "inline_requests",
        ]
        return {key: safe_float(row[i]) for i, key in enumerate(metric_keys)}

    def _calculate_change_pct(self, current: float, previous: float) -> float:
        """Calculate percentage change from previous period."""
        if previous > 0:
            return ((current - previous) / previous) * 100
        elif current > 0:
            return 100.0  # New activity
        return 0.0
