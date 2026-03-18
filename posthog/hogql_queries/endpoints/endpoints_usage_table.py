from typing import Literal, cast

from posthog.schema import (
    CachedEndpointsUsageTableQueryResponse,
    EndpointsUsageBreakdown,
    EndpointsUsageTableQuery,
    EndpointsUsageTableQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.endpoints.endpoints_usage_query_runner import EndpointsUsageQueryRunner


class EndpointsUsageTableQueryRunner(EndpointsUsageQueryRunner[EndpointsUsageTableQueryResponse]):
    """Returns breakdown table for endpoint usage.

    Supports breaking down by:
    - Endpoint: Group by endpoint name
    - MaterializationType: Group by materialized vs inline
    - ApiKey: Group by API key
    - Status: Group by success vs error
    """

    query: EndpointsUsageTableQuery
    cached_response: CachedEndpointsUsageTableQueryResponse

    def to_query(self) -> ast.SelectQuery:
        # Build WHERE conditions
        conditions = self._get_base_where_conditions()
        where_clause = ast.And(exprs=conditions) if len(conditions) > 1 else conditions[0] if conditions else None

        # Get breakdown expression and alias
        breakdown_expr, breakdown_alias = self._get_table_breakdown_expression()

        # Build ORDER BY
        order_by = self._get_order_by()

        # Build LIMIT and OFFSET
        limit = self.query.limit or 100
        offset = self.query.offset or 0

        return ast.SelectQuery(
            select=[
                ast.Alias(alias=breakdown_alias, expr=breakdown_expr),
                ast.Alias(alias="requests", expr=self._get_requests_count_expression()),
                ast.Alias(alias="bytes_read", expr=self._get_bytes_read_expression()),
                ast.Alias(alias="cpu_seconds", expr=self._get_cpu_seconds_expression()),
                ast.Alias(alias="avg_query_duration_ms", expr=self._get_avg_latency_expression()),
                ast.Alias(alias="error_rate", expr=self._get_error_rate_expression()),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["query_log"])),
            where=where_clause,
            group_by=[breakdown_expr],
            order_by=order_by,
            limit=ast.Constant(value=limit),
            offset=ast.Constant(value=offset),
        )

    def _get_table_breakdown_expression(self) -> tuple[ast.Expr, str]:
        """Get the expression and alias for the table breakdown column.

        Unlike the base class method which uses a uniform alias, this returns
        context-specific aliases for the table display (e.g., 'endpoint', 'execution_type').
        """
        breakdown = self.query.breakdownBy
        alias_map = {
            EndpointsUsageBreakdown.ENDPOINT: "endpoint",
            EndpointsUsageBreakdown.MATERIALIZATION_TYPE: "execution_type",
            EndpointsUsageBreakdown.API_KEY: "api_key",
            EndpointsUsageBreakdown.STATUS: "status",
        }
        alias = alias_map.get(breakdown, "endpoint")
        expr, _ = super()._get_breakdown_expression(breakdown, alias)
        return expr, alias

    def _get_order_by(self) -> list[ast.OrderExpr]:
        """Build ORDER BY clause based on query settings."""
        order_by = self.query.orderBy

        if not order_by:
            # Default: order by requests descending
            return [ast.OrderExpr(expr=ast.Field(chain=["requests"]), order="DESC")]

        field_name, direction = order_by

        # Map field names to column aliases
        field_map = {
            "requests": "requests",
            "bytes_read": "bytes_read",
            "cpu_seconds": "cpu_seconds",
            "avg_latency": "avg_query_duration_ms",
            "error_rate": "error_rate",
        }

        column = field_map.get(field_name, "requests")
        order_direction = direction if direction in ("ASC", "DESC") else "DESC"

        return [ast.OrderExpr(expr=ast.Field(chain=[column]), order=cast(Literal["ASC", "DESC"], order_direction))]

    def _calculate(self) -> EndpointsUsageTableQueryResponse:
        from posthog.clickhouse.query_tagging import tag_queries

        tag_queries(name="endpoints_usage_table")
        response = execute_hogql_query(
            query_type="endpoints_usage_table_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        # Determine if there are more results
        limit = self.query.limit or 100
        has_more = len(response.results) >= limit if response.results else False

        return EndpointsUsageTableQueryResponse(
            results=response.results or [],
            columns=response.columns,
            types=response.types,
            hasMore=has_more,
            limit=limit,
            offset=self.query.offset or 0,
            timings=response.timings,
            hogql=response.hogql,
        )
