from datetime import datetime, timedelta
from functools import cached_property
from typing import cast

from posthog.schema import (
    CachedTracesNeighborsQueryResponse,
    IntervalType,
    TracesNeighborsQuery,
    TracesNeighborsQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange


class TracesNeighborsQueryRunner(AnalyticsQueryRunner[TracesNeighborsQueryResponse]):
    """
    Query runner to find the previous and next traces relative to a given trace.
    Used for next/previous navigation in the trace detail view.
    """

    query: TracesNeighborsQuery
    cached_response: CachedTracesNeighborsQueryResponse

    def _calculate(self):
        # Parse the current trace's timestamp
        current_timestamp = datetime.fromisoformat(self.query.timestamp.replace("Z", "+00:00"))

        # Get previous trace (most recent before current)
        prev_trace_id, prev_timestamp = self._get_neighbor_trace(current_timestamp, direction="prev")

        # Get next trace (oldest after current)
        next_trace_id, next_timestamp = self._get_neighbor_trace(current_timestamp, direction="next")

        return TracesNeighborsQueryResponse(
            prevTraceId=prev_trace_id,
            prevTimestamp=prev_timestamp,
            nextTraceId=next_trace_id,
            nextTimestamp=next_timestamp,
        )

    def _get_neighbor_trace(self, current_timestamp: datetime, direction: str) -> tuple[str | None, str | None]:
        """Get the previous or next trace relative to the current timestamp."""
        if direction == "prev":
            # Previous = most recent trace before current (or same timestamp but earlier trace_id)
            comparison_op = "<"
            order = "DESC"
        else:
            # Next = oldest trace after current (or same timestamp but later trace_id)
            comparison_op = ">"
            order = "ASC"

        with self.timings.measure(f"traces_neighbors_{direction}"), tags_context(product=Product.LLM_ANALYTICS):
            # Use a subquery to first get max timestamp per trace, then filter
            # Use tuple comparison (timestamp, trace_id) to handle identical timestamps deterministically
            query = parse_select(
                f"""
                SELECT trace_id, trace_timestamp
                FROM (
                    SELECT
                        properties.$ai_trace_id as trace_id,
                        max(timestamp) as trace_timestamp
                    FROM events
                    WHERE event IN ('$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace')
                      AND {{conditions}}
                    GROUP BY properties.$ai_trace_id
                )
                WHERE (trace_timestamp, trace_id) {comparison_op} ({{current_timestamp}}, {{current_trace_id}})
                ORDER BY trace_timestamp {order}, trace_id {order}
                LIMIT 1
                """,
            )

            result = execute_hogql_query(
                query_type=f"TracesNeighborsQuery_{direction}",
                query=query,
                placeholders={
                    "conditions": self._get_filter_conditions(),
                    "current_timestamp": ast.Constant(value=current_timestamp),
                    "current_trace_id": ast.Constant(value=self.query.traceId),
                },
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
            )

            if not result.results or len(result.results) == 0:
                return None, None

            trace_id, timestamp = result.results[0]
            return str(trace_id) if trace_id else None, timestamp.isoformat() if timestamp else None

    def _get_filter_conditions(self) -> ast.Expr:
        """Build the filter conditions, similar to TracesQueryRunner."""
        exprs: list[ast.Expr] = [
            # Trace ID must exist and not be empty
            ast.Call(name="isNotNull", args=[ast.Field(chain=["properties", "$ai_trace_id"])]),
            ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq,
                left=ast.Field(chain=["properties", "$ai_trace_id"]),
                right=ast.Constant(value=""),
            ),
            # Date range filter (current trace exclusion is handled by tuple comparison in query)
            self._get_date_range_filter(),
        ]

        # Property filters
        properties_filter = self._get_properties_filter()
        if properties_filter is not None:
            exprs.append(properties_filter)

        # Test accounts filter
        if self.query.filterTestAccounts:
            with self.timings.measure("test_account_filters"):
                for prop in self.team.test_account_filters or []:
                    exprs.append(property_to_expr(prop, self.team))

        # Support traces filter
        if self.query.filterSupportTraces:
            exprs.append(
                ast.Or(
                    exprs=[
                        ast.Call(name="isNull", args=[ast.Field(chain=["properties", "ai_support_impersonated"])]),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.NotEq,
                            left=ast.Field(chain=["properties", "ai_support_impersonated"]),
                            right=ast.Constant(value="true"),
                        ),
                    ]
                )
            )

        return ast.And(exprs=exprs)

    def _get_properties_filter(self) -> ast.Expr | None:
        """Build property filters from query properties."""
        if not self.query.properties:
            return None

        property_filters: list[ast.Expr] = []
        with self.timings.measure("property_filters"):
            for prop in self.query.properties:
                property_filters.append(property_to_expr(prop, self.team))

        if not property_filters:
            return None

        return ast.And(exprs=property_filters)

    def _get_date_range_filter(self) -> ast.Expr:
        """Build date range filter."""
        return ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["events", "timestamp"]),
                    right=self._date_range.date_from_as_hogql(),
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["events", "timestamp"]),
                    right=self._date_range.date_to_as_hogql(),
                ),
            ]
        )

    @cached_property
    def _date_range(self):
        # Use the provided date range, or fall back to a wide range centered around the trace timestamp
        if self.query.dateRange and (self.query.dateRange.date_from or self.query.dateRange.date_to):
            return QueryDateRange(self.query.dateRange, self.team, IntervalType.MINUTE, datetime.now())

        # Default: 30 days before and after the trace timestamp for finding neighbors
        from posthog.schema import DateRange

        trace_ts = datetime.fromisoformat(self.query.timestamp.replace("Z", "+00:00"))
        return QueryDateRange(
            DateRange(
                date_from=(trace_ts - timedelta(days=30)).isoformat(),
                date_to=(trace_ts + timedelta(days=30)).isoformat(),
            ),
            self.team,
            IntervalType.MINUTE,
            datetime.now(),
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """Required by base class but not used for this query type."""
        # Return a simple placeholder query - the actual work is done in _calculate
        return cast(ast.SelectQuery, parse_select("SELECT 1"))
