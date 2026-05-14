from datetime import datetime, timedelta
from functools import cached_property
from typing import Any, Optional, cast

import orjson

from posthog.schema import (
    CachedTraceQueryResponse,
    IntervalType,
    LLMTrace,
    LLMTraceEvent,
    NodeKind,
    TraceQuery,
    TraceQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr

from posthog.hogql_queries.ai.ai_table_resolver import execute_with_ai_events_fallback
from posthog.hogql_queries.ai.utils import merge_heavy_properties
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

TRACE_FIELDS_MAPPING: dict[str, str] = {
    "id": "id",
    "ai_session_id": "aiSessionId",
    "created_at": "createdAt",
    "first_distinct_id": "distinctId",
    "total_latency": "totalLatency",
    "input_state_parsed": "inputState",
    "output_state_parsed": "outputState",
    "input_tokens": "inputTokens",
    "output_tokens": "outputTokens",
    "input_cost": "inputCost",
    "output_cost": "outputCost",
    "total_cost": "totalCost",
    "events": "events",
    "trace_name": "traceName",
}


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


class TraceQueryRunner(AnalyticsQueryRunner[TraceQueryResponse]):
    query: TraceQuery
    cached_response: CachedTraceQueryResponse

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)

    def _calculate(self):
        query_result = execute_with_ai_events_fallback(
            query=self._build_query(),
            placeholders={"filter_conditions": self._get_where_clause()},
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
                max(timestamp) AS last_timestamp,
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
                                   parent_id IS NULL
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
            FROM posthog.ai_events AS ai_events
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
            "schema_version": 5,
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

    def _map_event(self, event_tuple: tuple) -> LLMTraceEvent:
        event_uuid, event_name, event_timestamp, event_properties, *heavy = event_tuple
        heavy_columns = dict(zip(("input", "output", "output_choices", "input_state", "output_state", "tools"), heavy))
        generation: dict[str, Any] = {
            "id": str(event_uuid),
            "event": event_name,
            "createdAt": event_timestamp.isoformat(),
            "properties": merge_heavy_properties(event_properties, heavy_columns),
        }
        return LLMTraceEvent.model_validate(generation)

    def _map_trace(self, result: dict[str, Any], created_at: datetime) -> LLMTrace:
        generations = []
        for event_tuple in result["events"]:
            generations.append(self._map_event(event_tuple))

        trace_dict = {
            **result,
            "created_at": created_at.isoformat(),
            "events": generations,
        }
        for raw_key, parsed_key in [("input_state", "input_state_parsed"), ("output_state", "output_state_parsed")]:
            raw = trace_dict.get(raw_key) or None
            trace_dict[raw_key] = raw
            if raw is not None:
                try:
                    trace_dict[parsed_key] = orjson.loads(raw)
                except (TypeError, orjson.JSONDecodeError):
                    trace_dict[parsed_key] = raw
        trace = LLMTrace.model_validate(
            {TRACE_FIELDS_MAPPING[key]: value for key, value in trace_dict.items() if key in TRACE_FIELDS_MAPPING}
        )
        return trace

    def _map_results(self, columns: list[str], query_results: list) -> list[LLMTrace]:
        mapped_results = [dict(zip(columns, value)) for value in query_results]
        traces = []

        date_from = self._date_range.date_from_for_filtering()
        date_to = self._date_range.date_to_for_filtering()

        for result in mapped_results:
            # Overlap semantics: match sessions list behavior where a trace
            # is counted if ANY of its events fall in the date window.
            first_timestamp = cast(datetime, result["first_timestamp"])
            last_timestamp = cast(datetime, result["last_timestamp"])
            if first_timestamp > date_to or last_timestamp < date_from:
                continue

            traces.append(self._map_trace(result, first_timestamp))

        return traces
