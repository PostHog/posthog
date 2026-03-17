from datetime import datetime, timedelta
from functools import cached_property
from typing import Optional, cast

from posthog.schema import CachedTraceQueryResponse, IntervalType, NodeKind, TraceQuery, TraceQueryResponse

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.hogql_queries.ai.ai_column_rewriter import rewrite_expr_for_events_table, rewrite_query_for_events_table
from posthog.hogql_queries.ai.ai_property_rewriter import rewrite_expr_for_ai_events_table
from posthog.hogql_queries.ai.ai_table_resolver import is_ai_events_enabled, is_within_ai_events_ttl
from posthog.hogql_queries.ai.utils import TraceMapperMixin
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange


class TraceQueryDateRange(QueryDateRange):
    """
    Extends the QueryDateRange to include a capture range of 10 minutes before and after the date range.
    It's a naive assumption that a trace finishes generating within 10 minutes of the first event so we can apply the date filters.
    """

    CAPTURE_RANGE_MINUTES = 10

    def date_from_for_filtering(self) -> datetime:
        return super().date_from()

    def date_to_for_filtering(self) -> datetime:
        return super().date_to()

    def date_from(self) -> datetime:
        return super().date_from() - timedelta(minutes=self.CAPTURE_RANGE_MINUTES)

    def date_to(self) -> datetime:
        return super().date_to() + timedelta(minutes=self.CAPTURE_RANGE_MINUTES)


class TraceQueryRunner(TraceMapperMixin, AnalyticsQueryRunner[TraceQueryResponse]):
    query: TraceQuery
    cached_response: CachedTraceQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _should_use_ai_events_table(self) -> bool:
        if not is_ai_events_enabled(self.team):
            return False
        return is_within_ai_events_ttl(self._date_range.date_from(), datetime.now())

    def _calculate(self):
        query = self._build_query()
        placeholders: dict[str, ast.Expr] = {"filter_conditions": self._get_where_clause()}

        if not self._should_use_ai_events_table():
            query = cast(ast.SelectQuery, rewrite_query_for_events_table(query))
            placeholders = {k: rewrite_expr_for_events_table(v) for k, v in placeholders.items()}
        else:
            placeholders = {k: rewrite_expr_for_ai_events_table(v) for k, v in placeholders.items()}

        with self.timings.measure("trace_query_hogql_execute"), tags_context(product=Product.LLM_ANALYTICS):
            query_result = execute_hogql_query(
                query=query,
                placeholders=placeholders,
                team=self.team,
                query_type=NodeKind.TRACE_QUERY,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        columns: list[str] = query_result.columns or []
        results = self._map_results(columns, query_result.results)

        return TraceQueryResponse(
            columns=columns,
            results=results,
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
        )

    def to_query(self):
        return self._build_query()

    def _build_query(self) -> ast.SelectQuery:
        query = parse_select(
            """
            SELECT
                trace_id AS id,
                any(session_id) AS ai_session_id,
                min(timestamp) AS first_timestamp,
                ifNull(
                    nullIf(argMinIf(distinct_id, timestamp, event = '$ai_trace'), ''),
                    argMin(distinct_id, timestamp)
                ) AS first_distinct_id,
                round(
                    CASE
                        -- If all events with latency are generations, sum them all
                        WHEN countIf(latency > 0 AND event != '$ai_generation') = 0
                             AND countIf(latency > 0 AND event = '$ai_generation') > 0
                        THEN sumIf(latency,
                                   event = '$ai_generation' AND latency > 0
                             )
                        -- Otherwise sum the direct children of the trace
                        ELSE sumIf(latency,
                                   parent_id = ''
                                   OR parent_id = trace_id
                             )
                    END, 2
                ) AS total_latency,
                nullIf(sumIf(input_tokens,
                      event IN ('$ai_generation', '$ai_embedding')
                ), 0) AS input_tokens,
                nullIf(sumIf(output_tokens,
                      event IN ('$ai_generation', '$ai_embedding')
                ), 0) AS output_tokens,
                nullIf(round(
                    sumIf(input_cost_usd,
                          event IN ('$ai_generation', '$ai_embedding')
                    ), 10
                ), 0) AS input_cost,
                nullIf(round(
                    sumIf(output_cost_usd,
                          event IN ('$ai_generation', '$ai_embedding')
                    ), 10
                ), 0) AS output_cost,
                nullIf(round(
                    sumIf(total_cost_usd,
                          event IN ('$ai_generation', '$ai_embedding')
                    ), 10
                ), 0) AS total_cost,
                arrayDistinct(
                    arraySort(
                        x -> x.3,
                        groupArrayIf(
                            tuple(uuid, event, timestamp, properties,
                                  input, output, output_choices, input_state, output_state, tools),
                            event != '$ai_trace'
                        )
                    )
                ) AS events,
                argMinIf(input_state,
                         timestamp, event = '$ai_trace'
                ) AS input_state,
                argMinIf(output_state,
                         timestamp, event = '$ai_trace'
                ) AS output_state,
                ifNull(
                    argMinIf(
                        ifNull(nullIf(span_name, ''), nullIf(trace_name, '')),
                        timestamp,
                        event = '$ai_trace'
                    ),
                    argMin(
                        ifNull(nullIf(span_name, ''), nullIf(trace_name, '')),
                        timestamp,
                    )
                ) AS trace_name
            FROM ai_events
            WHERE event IN (
                '$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace'
            )
              AND {filter_conditions}
            GROUP BY trace_id
            LIMIT 1
            """,
        )
        return cast(ast.SelectQuery, query)

    def get_cache_payload(self):
        return {
            **super().get_cache_payload(),
            # When the response schema changes, increment this version to invalidate the cache.
            "schema_version": 4,
        }

    @cached_property
    def _date_range(self):
        # Minute-level precision for 10m capture range
        return TraceQueryDateRange(self.query.dateRange, self.team, IntervalType.MINUTE, datetime.now())

    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        if last_refresh is None:
            return None

        return last_refresh + timedelta(minutes=1)

    def _get_where_clause(self) -> ast.Expr:
        where_exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["ai_events", "timestamp"]),
                right=self._date_range.date_from_as_hogql(),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["ai_events", "timestamp"]),
                right=self._date_range.date_to_as_hogql(),
            ),
        ]

        where_exprs.append(
            ast.CompareOperation(
                left=ast.Field(chain=["trace_id"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=self.query.traceId),
            ),
        )

        if self.query.properties:
            with self.timings.measure("property_filters"):
                for prop in self.query.properties:
                    where_exprs.append(property_to_expr(prop, self.team))

        return ast.And(exprs=where_exprs)
