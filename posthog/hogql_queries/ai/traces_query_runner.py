from datetime import datetime, timedelta
from functools import cached_property
from typing import cast

from posthog.schema import (
    CachedTracesQueryResponse,
    DateRange,
    IntervalType,
    NodeKind,
    TracesQuery,
    TracesQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_TRACES_LIMIT_EXPORT, LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.hogql_queries.ai.ai_column_rewriter import rewrite_expr_for_events_table, rewrite_query_for_events_table
from posthog.hogql_queries.ai.ai_property_rewriter import rewrite_expr_for_ai_events_table
from posthog.hogql_queries.ai.ai_table_resolver import is_ai_events_enabled, is_within_ai_events_ttl
from posthog.hogql_queries.ai.utils import TraceMapperMixin
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange


class TracesQueryDateRange(QueryDateRange):
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


class TracesQueryRunner(TraceMapperMixin, AnalyticsQueryRunner[TracesQueryResponse]):
    query: TracesQuery
    cached_response: CachedTracesQueryResponse
    TRACE_FIELDS_MAPPING = {
        **TraceMapperMixin.TRACE_FIELDS_MAPPING,
        "error_count": "errorCount",
        "is_support_trace": "isSupportTrace",
        "tools": "tools",
    }

    paginator: HogQLHasMorePaginator
    _trace_ids: list[str] | None = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        limit = self.query.limit
        if self.limit_context == LimitContext.EXPORT:
            limit = min(limit or MAX_SELECT_TRACES_LIMIT_EXPORT, MAX_SELECT_TRACES_LIMIT_EXPORT)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=self.limit_context,
            limit=limit,
            offset=self.query.offset,
        )

    def _should_use_ai_events_table(self) -> bool:
        if not is_ai_events_enabled(self.team):
            return False
        return is_within_ai_events_ttl(self._date_range.date_from(), datetime.now())

    def _get_trace_ids(self) -> tuple[list[str], datetime | None, datetime | None]:
        """Execute a separate query to get relevant trace IDs and their time range."""
        with self.timings.measure("traces_query_trace_ids_execute"), tags_context(product=Product.LLM_ANALYTICS):
            # Calculate max number of events needed with current offset and limit
            limit_value = self.paginator.limit
            offset_value = self.paginator.offset
            pagination_limit = limit_value + offset_value + 1

            # The subquery ordering must match the main query's ORDER BY first_timestamp DESC
            # (where first_timestamp = min(timestamp)). Using a different ordering here (e.g.
            # max(timestamp)) causes pagination bugs: the subquery selects trace IDs in one
            # order but the main query re-sorts them differently, so OFFSET-based slicing
            # produces overlapping or missing traces across pages.
            order_clause = "rand()" if self.query.randomOrder else "min(timestamp) DESC"

            trace_ids_query = parse_select(
                f"""
                SELECT
                    groupArray(trace_id) as trace_ids,
                    min(first_ts) as min_timestamp,
                    max(last_ts) as max_timestamp
                FROM (
                    SELECT
                        trace_id AS trace_id,
                        min(timestamp) as first_ts,
                        max(timestamp) as last_ts
                    FROM ai_events
                    WHERE event IN ('$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace')
                      AND {{conditions}}
                    GROUP BY trace_id
                    ORDER BY {order_clause}
                    LIMIT {{limit}}
                )
                """,
            )

            placeholders: dict[str, ast.Expr] = {
                "conditions": self._get_subquery_filter(),
                "limit": ast.Constant(value=pagination_limit),
            }

            if not self._should_use_ai_events_table():
                trace_ids_query = rewrite_query_for_events_table(trace_ids_query)
                placeholders = {k: rewrite_expr_for_events_table(v) for k, v in placeholders.items()}
            else:
                placeholders = {k: rewrite_expr_for_ai_events_table(v) for k, v in placeholders.items()}

            trace_ids_result = execute_hogql_query(
                query_type="TracesQuery_TraceIds",
                query=trace_ids_query,
                placeholders=placeholders,
                team=self.team,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

            # Extract trace IDs and time range from results
            if not trace_ids_result.results or not trace_ids_result.results[0]:
                return [], None, None

            trace_ids_array, min_timestamp, max_timestamp = trace_ids_result.results[0]

            # Filter out any null/empty trace IDs and convert to strings
            trace_ids = [str(tid) for tid in (trace_ids_array or []) if tid]

            return trace_ids, min_timestamp, max_timestamp

    def _calculate(self):
        trace_ids, min_timestamp, max_timestamp = self._get_trace_ids()

        # If no trace IDs found, return empty results
        if not trace_ids:
            return TracesQueryResponse(
                columns=[],
                results=[],
                timings=self.timings.to_list(),
                hogql="",
                modifiers=self.modifiers,
                **self.paginator.response_params(),
            )

        # Store trace_ids for use in to_query
        self._trace_ids = trace_ids

        # Create a narrowed date range if we have timestamps
        narrowed_date_range = self._create_narrowed_date_range(min_timestamp, max_timestamp)

        query = self._to_query_with_trace_ids(trace_ids)
        placeholders: dict[str, ast.Expr] = {
            "filter_conditions": self._get_where_clause(date_range=narrowed_date_range),
        }

        if not self._should_use_ai_events_table():
            query = rewrite_query_for_events_table(query)
            placeholders = {k: rewrite_expr_for_events_table(v) for k, v in placeholders.items()}
        else:
            placeholders = {k: rewrite_expr_for_ai_events_table(v) for k, v in placeholders.items()}

        with self.timings.measure("traces_query_hogql_execute"), tags_context(product=Product.LLM_ANALYTICS):
            query_result = self.paginator.execute_hogql_query(
                query=query,
                placeholders=placeholders,
                team=self.team,
                query_type=NodeKind.TRACES_QUERY,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        columns: list[str] = query_result.columns or []
        results = self._map_results(columns, query_result.results)

        return TracesQueryResponse(
            columns=columns,
            results=results,
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        """Public method matching the base class signature."""
        if self._trace_ids is None:
            # If called before _calculate, run the trace_ids query
            trace_ids, _, _ = self._get_trace_ids()
            self._trace_ids = trace_ids if trace_ids else []

        return self._to_query_with_trace_ids(self._trace_ids)

    def _to_query_with_trace_ids(self, trace_ids: list[str]) -> ast.SelectQuery | ast.SelectSetQuery:
        """Internal method that builds the query with specific trace IDs."""
        # Separate query to build the trace IDs tuple for the IN clause
        # Without using a tuple, the data skipping index is not used
        trace_ids_tuple = ast.Tuple(exprs=[ast.Constant(value=tid) for tid in trace_ids])

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
                    arraySort(x -> x.3,
                        groupArrayIf(
                            tuple(uuid, event, timestamp, properties,
                                  input, output, output_choices, input_state, output_state, tools),
                            event IN ('$ai_metric', '$ai_feedback') OR parent_id = trace_id
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
                ) AS trace_name,
                countIf(
                    is_error = 1
                ) AS error_count,
                any(properties.ai_support_impersonated) AS is_support_trace,
                arrayFilter(
                    x -> x != '',
                    arrayDistinct(
                        splitByChar(',',
                            arrayStringConcat(
                                groupArrayIf(
                                    toString(properties.$ai_tools_called),
                                    event = '$ai_generation'
                                    AND isNotNull(properties.$ai_tools_called)
                                    AND toString(properties.$ai_tools_called) != ''
                                ),
                                ','
                            )
                        )
                    )
                ) AS tools
            FROM ai_events
            WHERE event IN (
                '$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace'
            )
              AND {filter_conditions}
            GROUP BY trace_id
            ORDER BY first_timestamp DESC
            """,
        )

        # Add the trace IDs filter to the WHERE clause
        query = cast(ast.SelectQuery, query)

        trace_id_filter = ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["trace_id"]),
            right=trace_ids_tuple,
        )

        if query.where:
            query.where = ast.And(exprs=[query.where, trace_id_filter])
        else:
            query.where = trace_id_filter

        return query

    def get_cache_payload(self):
        return {
            **super().get_cache_payload(),
            # When the response schema changes, increment this version to invalidate the cache.
            "schema_version": 6,
        }

    @cached_property
    def _date_range(self):
        # Minute-level precision for 10m capture range
        return TracesQueryDateRange(self.query.dateRange, self.team, IntervalType.MINUTE, datetime.now())

    def _create_narrowed_date_range(
        self, min_timestamp: datetime | None, max_timestamp: datetime | None
    ) -> TracesQueryDateRange | None:
        """Create a narrowed date range based on the actual data timestamps."""
        if min_timestamp is None or max_timestamp is None:
            return None

        # Create a custom date range with the min/max timestamps
        # The TracesQueryDateRange class will automatically add the 10-minute capture range buffer
        # through its overridden date_from() and date_to() methods
        narrowed_range = TracesQueryDateRange(
            DateRange(date_from=min_timestamp.isoformat(), date_to=max_timestamp.isoformat(), explicitDate=True),
            self.team,
            IntervalType.MINUTE,
            datetime.now(),
        )

        return narrowed_range

    def _get_subquery_filter(self) -> ast.Expr:
        exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq,
                left=ast.Field(chain=["trace_id"]),
                right=ast.Constant(value=""),
            ),
            self._get_where_clause(),
        ]

        properties_filter = self._get_properties_filter()
        if properties_filter is not None:
            exprs.append(properties_filter)

        if self.query.personId:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["person_id"]),
                    right=ast.Constant(value=self.query.personId),
                )
            )

        if self.query.groupKey and self.query.groupTypeIndex is not None:
            exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["properties", f"$group_{self.query.groupTypeIndex}"]),
                    right=ast.Constant(value=self.query.groupKey),
                )
            )

        return ast.And(exprs=exprs)

    def _get_properties_filter(self) -> ast.Expr | None:
        property_filters: list[ast.Expr] = []
        if self.query.properties:
            with self.timings.measure("property_filters"):
                for prop in self.query.properties:
                    property_filters.append(property_to_expr(prop, self.team))

        if not property_filters:
            return None

        return ast.And(exprs=property_filters)

    def _get_where_clause(self, date_range: TracesQueryDateRange | None = None) -> ast.Expr:
        # Use the provided date range or fall back to the default
        effective_date_range = date_range if date_range is not None else self._date_range

        where_exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=ast.Field(chain=["ai_events", "timestamp"]),
                right=effective_date_range.date_from_as_hogql(),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=ast.Field(chain=["ai_events", "timestamp"]),
                right=effective_date_range.date_to_as_hogql(),
            ),
        ]

        if self.query.filterTestAccounts:
            with self.timings.measure("test_account_filters"):
                for prop in self.team.test_account_filters or []:
                    where_exprs.append(property_to_expr(prop, self.team))

        if self.query.filterSupportTraces:
            where_exprs.append(
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

        return ast.And(exprs=where_exprs)

    def _get_order_by_clause(self):
        return [ast.OrderExpr(expr=ast.Field(chain=["trace_timestamp"]), order="DESC")]
