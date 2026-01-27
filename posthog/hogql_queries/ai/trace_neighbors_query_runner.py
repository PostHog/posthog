from datetime import datetime, timedelta
from functools import cached_property
from typing import cast

from posthog.schema import (
    CachedTraceNeighborsQueryResponse,
    IntervalType,
    TraceNeighborsQuery,
    TraceNeighborsQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange


class TraceNeighborsQueryRunner(AnalyticsQueryRunner[TraceNeighborsQueryResponse]):
    """
    Query runner to find the older and newer traces relative to a given trace.
    Used for older/newer navigation in the trace detail view.
    """

    query: TraceNeighborsQuery
    cached_response: CachedTraceNeighborsQueryResponse

    def _calculate(self):
        with self.timings.measure("trace_neighbors"), tags_context(product=Product.LLM_ANALYTICS):
            result = execute_hogql_query(
                query_type="TraceNeighborsQuery",
                query=self.to_query(),
                placeholders=self._get_placeholders(),
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
            )

            # Parse results - could have 0, 1, or 2 rows
            older_trace_id, older_timestamp = None, None
            newer_trace_id, newer_timestamp = None, None

            for row in result.results:
                direction, trace_id, timestamp = row
                if direction == "older":
                    older_trace_id = str(trace_id) if trace_id else None
                    older_timestamp = timestamp.isoformat() if timestamp else None
                elif direction == "newer":
                    newer_trace_id = str(trace_id) if trace_id else None
                    newer_timestamp = timestamp.isoformat() if timestamp else None

            return TraceNeighborsQueryResponse(
                olderTraceId=older_trace_id,
                olderTimestamp=older_timestamp,
                newerTraceId=newer_trace_id,
                newerTimestamp=newer_timestamp,
            )

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
            # Date range filter
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
        # Use the provided date range, or fall back to a range centered around the trace timestamp
        if self.query.dateRange and (self.query.dateRange.date_from or self.query.dateRange.date_to):
            return QueryDateRange(self.query.dateRange, self.team, IntervalType.MINUTE, datetime.now())

        # Default: 3 days before and after the trace timestamp for finding neighbors
        # This is more performant for large customers while still covering most navigation scenarios
        from posthog.schema import DateRange

        trace_ts = datetime.fromisoformat(self.query.timestamp.replace("Z", "+00:00"))
        return QueryDateRange(
            DateRange(
                date_from=(trace_ts - timedelta(days=3)).isoformat(),
                date_to=(trace_ts + timedelta(days=3)).isoformat(),
            ),
            self.team,
            IntervalType.MINUTE,
            datetime.now(),
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """
        Build a query that finds both older and newer traces using UNION ALL.
        Uses tuple comparison (timestamp, trace_id) to handle identical timestamps deterministically.
        """
        query = parse_select(
            """
            SELECT
                'older' as direction,
                trace_id,
                trace_timestamp
            FROM (
                SELECT
                    properties.$ai_trace_id as trace_id,
                    max(timestamp) as trace_timestamp
                FROM events
                WHERE event IN ('$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace')
                  AND timestamp <= {current_timestamp}
                  AND {conditions}
                GROUP BY properties.$ai_trace_id
                HAVING (trace_timestamp, trace_id) < ({current_timestamp}, {current_trace_id})
                ORDER BY trace_timestamp DESC, trace_id DESC
                LIMIT 1
            )

            UNION ALL

            SELECT
                'newer' as direction,
                trace_id,
                trace_timestamp
            FROM (
                SELECT
                    properties.$ai_trace_id as trace_id,
                    max(timestamp) as trace_timestamp
                FROM events
                WHERE event IN ('$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace')
                  AND timestamp >= {current_timestamp}
                  AND {conditions}
                GROUP BY properties.$ai_trace_id
                HAVING (trace_timestamp, trace_id) > ({current_timestamp}, {current_trace_id})
                ORDER BY trace_timestamp ASC, trace_id ASC
                LIMIT 1
            )
            """,
        )
        return cast(ast.SelectSetQuery, query)

    def _get_placeholders(self) -> dict[str, ast.Expr]:
        """Build placeholders for the query."""
        current_timestamp = datetime.fromisoformat(self.query.timestamp.replace("Z", "+00:00"))
        return {
            "conditions": self._get_filter_conditions(),
            "current_timestamp": ast.Constant(value=current_timestamp),
            "current_trace_id": ast.Constant(value=self.query.traceId),
        }
