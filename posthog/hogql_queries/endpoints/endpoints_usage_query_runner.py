import typing
from abc import ABC
from datetime import datetime
from typing import Union, cast

from posthog.schema import EndpointsUsageOverviewQuery, EndpointsUsageTableQuery, EndpointsUsageTrendsQuery

from posthog.hogql import ast

from posthog.hogql_queries.query_runner import AnalyticsQueryResponseProtocol, AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.filters.mixins.utils import cached_property

EndpointsUsageQueryNode = Union[
    EndpointsUsageOverviewQuery,
    EndpointsUsageTableQuery,
    EndpointsUsageTrendsQuery,
]

EAR = typing.TypeVar("EAR", bound=AnalyticsQueryResponseProtocol)


def safe_float(val: typing.Any) -> float:
    """Convert value to float, handling None and other edge cases."""
    if val is None:
        return 0.0
    try:
        return float(val)
    except (TypeError, ValueError):
        return 0.0


class EndpointsUsageQueryRunner(AnalyticsQueryRunner[EAR], ABC):
    """Base class for Endpoints usage queries.

    Queries the query_log table for endpoint execution metrics, filtering
    specifically for endpoint executions (not general API usage).
    """

    query: EndpointsUsageQueryNode
    query_type: type[EndpointsUsageQueryNode]

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=None,
            now=datetime.now(),
        )

    def _get_base_where_conditions(self) -> list[ast.Expr]:
        """Build base WHERE conditions for endpoint queries.

        Filters for:
        - Personal API key requests only (external API calls, not app usage)
        - Endpoint executions only (identified by having a non-empty name field)
        - Date range
        """
        conditions: list[ast.Expr] = []

        # Only include requests made via personal API keys (external API calls)
        # This excludes executions from the app itself
        conditions.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["is_personal_api_key_request"]),
                right=ast.Constant(value=True),
            )
        )

        # Filter for endpoint executions only
        # Endpoint executions are identified by having a non-empty lc_request_name.
        # The 'name' field in HogQL maps to lc_request_name in the underlying table.
        # Non-endpoint queries (like regular HogQL queries) have empty/null names.
        conditions.append(
            ast.Call(
                name="isNotNull",
                args=[ast.Field(chain=["name"])],
            )
        )
        conditions.append(
            ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq,
                left=ast.Field(chain=["name"]),
                right=ast.Constant(value=""),
            )
        )

        conditions.append(
            ast.Call(
                name="match",
                args=[
                    ast.Field(chain=["query_log", "endpoint"]),
                    ast.Constant(value=r"^/api/(environments|projects)/[0-9]+/endpoints/[^/]+/run/?$"),
                ],
            )
        )

        # Date range filter
        if self.query_date_range.date_from():
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["event_date"]),
                    right=ast.Constant(value=self.query_date_range.date_from()),
                )
            )
        if self.query_date_range.date_to():
            conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["event_date"]),
                    right=ast.Constant(value=self.query_date_range.date_to()),
                )
            )

        # Add endpoint names filter if specified
        endpoint_names_filter = self._get_endpoint_names_filter()
        if endpoint_names_filter:
            conditions.append(endpoint_names_filter)

        # Add materialization type filter if specified
        materialization_filter = self._get_materialization_filter()
        if materialization_filter:
            conditions.append(materialization_filter)

        return conditions

    def _get_endpoint_names_filter(self) -> ast.Expr | None:
        """Filter to specific endpoints if specified."""
        endpoint_names = getattr(self.query, "endpointNames", None)
        if not endpoint_names:
            return None

        # Create OR condition to match both regular and materialized names
        name_conditions = []
        for name in endpoint_names:
            name_conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["name"]),
                    right=ast.Constant(value=name),
                )
            )
            # Also match materialized version
            name_conditions.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["name"]),
                    right=ast.Constant(value=f"{name}_materialized"),
                )
            )

        return ast.Or(exprs=cast(list[ast.Expr], name_conditions))

    def _get_materialization_filter(self) -> ast.Expr | None:
        """Filter by materialization type if specified."""
        from posthog.schema import MaterializationType

        mat_type = getattr(self.query, "materializationType", None)
        if mat_type is None:
            return None

        if mat_type == MaterializationType.MATERIALIZED:
            # Name ends with "_materialized"
            return ast.CompareOperation(
                op=ast.CompareOperationOp.Like,
                left=ast.Field(chain=["name"]),
                right=ast.Constant(value="%_materialized"),
            )
        elif mat_type == MaterializationType.INLINE:
            return ast.Not(
                expr=ast.CompareOperation(
                    op=ast.CompareOperationOp.Like,
                    left=ast.Field(chain=["name"]),
                    right=ast.Constant(value="%_materialized"),
                )
            )
        else:
            # Unknown or None value, no filter
            return None

    def _get_endpoint_name_expression(self) -> ast.Expr:
        """Get an expression that strips '_materialized' suffix from endpoint names.

        This normalizes endpoint names so we can group materialized and non-materialized
        executions of the same endpoint together.
        """
        return ast.Call(
            name="replaceRegexpOne",
            args=[
                ast.Field(chain=["name"]),
                ast.Constant(value="_materialized$"),
                ast.Constant(value=""),
            ],
        )

    def _get_is_materialized_expression(self) -> ast.Expr:
        """Get an expression that returns whether this was a materialized execution."""
        return ast.Call(
            name="endsWith",
            args=[
                ast.Field(chain=["name"]),
                ast.Constant(value="_materialized"),
            ],
        )

    def _get_breakdown_expression(
        self, breakdown: typing.Any, default_alias: str = "breakdown"
    ) -> tuple[ast.Expr, str]:
        """Get the expression and alias for a breakdown column.

        Shared method used by both Trends and Table runners.
        """
        from posthog.schema import EndpointsUsageBreakdown

        if breakdown == EndpointsUsageBreakdown.ENDPOINT:
            return self._get_endpoint_name_expression(), default_alias

        elif breakdown == EndpointsUsageBreakdown.MATERIALIZATION_TYPE:
            return (
                ast.Call(
                    name="if",
                    args=[
                        self._get_is_materialized_expression(),
                        ast.Constant(value="Materialized execution"),
                        ast.Constant(value="Direct execution"),
                    ],
                ),
                default_alias,
            )

        elif breakdown == EndpointsUsageBreakdown.API_KEY:
            return ast.Field(chain=["api_key_label"]), default_alias

        elif breakdown == EndpointsUsageBreakdown.STATUS:
            return self._get_status_expression(), default_alias

        else:
            # Default to endpoint breakdown
            return self._get_endpoint_name_expression(), default_alias

    def _get_status_expression(self) -> ast.Expr:
        """Get an expression that returns 'success' or 'error' based on exception_code."""
        return ast.Call(
            name="if",
            args=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["exception_code"]),
                    right=ast.Constant(value=0),
                ),
                ast.Constant(value="success"),
                ast.Constant(value="error"),
            ],
        )

    def _get_error_rate_expression(self) -> ast.Expr:
        """Get an expression for calculating error rate (ratio of failed requests)."""
        return ast.ArithmeticOperation(
            op=ast.ArithmeticOperationOp.Div,
            left=ast.Call(
                name="countIf",
                args=[
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.NotEq,
                        left=ast.Field(chain=["exception_code"]),
                        right=ast.Constant(value=0),
                    )
                ],
            ),
            right=ast.Call(name="count", args=[]),
        )

    def _get_cpu_seconds_expression(self) -> ast.Expr:
        """Get an expression for CPU seconds (converted from microseconds)."""
        return ast.ArithmeticOperation(
            op=ast.ArithmeticOperationOp.Div,
            left=ast.Call(name="sum", args=[ast.Field(chain=["cpu_microseconds"])]),
            right=ast.Constant(value=1000000),
        )

    def _get_bytes_read_expression(self) -> ast.Expr:
        """Get an expression for total bytes read."""
        return ast.Call(name="sum", args=[ast.Field(chain=["read_bytes"])])

    def _get_requests_count_expression(self) -> ast.Expr:
        """Get an expression for request count."""
        return ast.Call(name="count", args=[])

    def _get_avg_latency_expression(self) -> ast.Expr:
        """Get an expression for average query duration in ms."""
        return ast.Call(name="avg", args=[ast.Field(chain=["query_duration_ms"])])

    def _get_p95_latency_expression(self) -> ast.Expr:
        """Get an expression for 95th percentile query duration in ms."""
        return ast.Call(
            name="quantile",
            params=[ast.Constant(value=0.95)],
            args=[ast.Field(chain=["query_duration_ms"])],
        )

    def _get_materialized_count_expression(self) -> ast.Expr:
        """Get an expression for count of materialized requests."""
        return ast.Call(
            name="countIf",
            args=[self._get_is_materialized_expression()],
        )

    def _get_inline_count_expression(self) -> ast.Expr:
        """Get an expression for count of inline (non-materialized) requests."""
        return ast.Call(
            name="countIf",
            args=[ast.Not(expr=self._get_is_materialized_expression())],
        )
