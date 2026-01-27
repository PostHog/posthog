from datetime import datetime
from typing import cast

from posthog.schema import (
    CachedEndpointsUsageTrendsQueryResponse,
    EndpointsUsageTrendsQuery,
    EndpointsUsageTrendsQueryResponse,
    IntervalType,
)

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.endpoints.endpoints_usage_query_runner import EndpointsUsageQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property


class EndpointsUsageTrendsQueryRunner(EndpointsUsageQueryRunner[EndpointsUsageTrendsQueryResponse]):
    """Returns time-series data for endpoint usage.

    Metrics available:
    - bytes_read: Sum of bytes read per time bucket
    - cpu_seconds: Sum of CPU seconds per time bucket
    - requests: Count of requests per time bucket
    - latency: Average latency per time bucket

    Can optionally break down by endpoint, materialization type, API key, or status.
    """

    query: EndpointsUsageTrendsQuery
    cached_response: CachedEndpointsUsageTrendsQueryResponse

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=self.query.interval or IntervalType.DAY,
            now=datetime.now(),
        )

    def to_query(self) -> ast.SelectQuery:
        # Build WHERE conditions
        conditions = self._get_base_where_conditions()
        where_clause = ast.And(exprs=conditions) if len(conditions) > 1 else conditions[0] if conditions else None

        # Get date bucket expression based on interval
        date_bucket_expr = self._get_date_bucket_expression()

        # Get metric expression
        metric_expr = self._get_metric_expression()

        # Build select columns
        select_columns = [
            ast.Alias(alias="date", expr=date_bucket_expr),
            ast.Alias(alias="value", expr=metric_expr),
        ]

        # Add breakdown column if specified
        group_by_columns: list[ast.Expr] = [date_bucket_expr]

        if self.query.breakdownBy:
            breakdown_expr, breakdown_alias = self._get_breakdown_expression(self.query.breakdownBy, "breakdown")
            select_columns.insert(1, ast.Alias(alias=breakdown_alias, expr=breakdown_expr))
            group_by_columns.append(breakdown_expr)

        return ast.SelectQuery(
            select=cast(list[ast.Expr], select_columns),
            select_from=ast.JoinExpr(table=ast.Field(chain=["query_log"])),
            where=where_clause,
            group_by=group_by_columns,
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=["date"]), order="ASC"),
            ],
        )

    def _get_date_bucket_expression(self) -> ast.Expr:
        """Get the expression for date bucketing based on interval."""
        interval = self.query.interval or IntervalType.DAY

        if interval == IntervalType.HOUR:
            return ast.Call(
                name="toStartOfHour",
                args=[ast.Field(chain=["event_time"])],
            )
        elif interval == IntervalType.DAY:
            return ast.Field(chain=["event_date"])
        elif interval == IntervalType.WEEK:
            return ast.Call(
                name="toStartOfWeek",
                args=[ast.Field(chain=["event_date"])],
            )
        elif interval == IntervalType.MONTH:
            return ast.Call(
                name="toStartOfMonth",
                args=[ast.Field(chain=["event_date"])],
            )
        else:
            # Default to day
            return ast.Field(chain=["event_date"])

    def _get_metric_expression(self) -> ast.Expr:
        """Get the expression for the selected metric."""
        metric = self.query.metric

        if metric == "bytes_read":
            return self._get_bytes_read_expression()
        elif metric == "cpu_seconds":
            return self._get_cpu_seconds_expression()
        elif metric == "requests":
            return self._get_requests_count_expression()
        elif metric == "query_duration":
            return self._get_avg_latency_expression()
        elif metric == "error_rate":
            return self._get_error_rate_expression()
        else:
            return self._get_requests_count_expression()

    def _calculate(self) -> EndpointsUsageTrendsQueryResponse:
        from posthog.clickhouse.query_tagging import tag_queries

        tag_queries(name="endpoints_usage_trends")
        response = execute_hogql_query(
            query_type="endpoints_usage_trends_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        # Transform results into the expected format
        # Each row is: [date, (breakdown,)? value]
        results: list[dict] = []

        if response.results:
            has_breakdown = self.query.breakdownBy is not None

            for row in response.results:
                if has_breakdown:
                    results.append(
                        {
                            "date": str(row[0]) if row[0] else None,
                            "breakdown": row[1],
                            "value": float(row[2]) if row[2] is not None else 0,
                        }
                    )
                else:
                    results.append(
                        {
                            "date": str(row[0]) if row[0] else None,
                            "value": float(row[1]) if row[1] is not None else 0,
                        }
                    )

        return EndpointsUsageTrendsQueryResponse(
            results=results,
            timings=response.timings,
            hogql=response.hogql,
        )
