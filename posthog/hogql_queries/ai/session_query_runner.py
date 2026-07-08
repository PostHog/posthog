from datetime import datetime, timedelta
from functools import cached_property
from typing import Any, Optional, cast

import orjson

from posthog.schema import (
    CachedSessionQueryResponse,
    IntervalType,
    LLMTrace,
    LLMTraceEvent,
    NodeKind,
    SessionQuery,
    SessionQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_TRACES_LIMIT_EXPORT, LimitContext
from posthog.hogql.parser import parse_select

from posthog.clickhouse.query_tagging import Product, tag_queries, tags_context
from posthog.hogql_queries.ai.ai_column_rewriter import (
    restore_events_result_alias,
    rewrite_expr_for_events_table,
    rewrite_query_for_events_table,
)
from posthog.hogql_queries.ai.ai_property_rewriter import rewrite_expr_for_ai_events_table
from posthog.hogql_queries.ai.sentiment_evaluations import (
    EMPTY_SENTIMENT_EVALUATION_LOOKUP,
    SentimentEvaluationLookup,
    get_generation_sentiment_lookup_ids,
    get_sentiment_for_generation,
    load_generation_sentiment_evaluations_for_traces,
)
from posthog.hogql_queries.ai.utils import merge_heavy_properties
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

SESSION_TRACE_FIELDS_MAPPING: dict[str, str] = {
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
    "request_cost": "requestCost",
    "web_search_cost": "webSearchCost",
    "total_cost": "totalCost",
    "events": "events",
    "trace_name": "traceName",
    "error_count": "errorCount",
    "is_support_trace": "isSupportTrace",
    "tools": "tools",
    "sentiment": "sentiment",
}


class SessionQueryRunner(AnalyticsQueryRunner[SessionQueryResponse]):
    query: SessionQuery
    cached_response: CachedSessionQueryResponse
    paginator: HogQLHasMorePaginator

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        limit = self.query.limit
        if self.limit_context == LimitContext.EXPORT:
            limit = min(limit or MAX_SELECT_TRACES_LIMIT_EXPORT, MAX_SELECT_TRACES_LIMIT_EXPORT)
        elif limit is not None:
            limit = min(limit, MAX_SELECT_TRACES_LIMIT_EXPORT)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=self.limit_context,
            limit=limit,
            offset=self.query.offset,
        )

    def _calculate(self) -> SessionQueryResponse:
        query = self._build_query()

        with self.timings.measure("session_query_ai_events_execute"), tags_context(product=Product.LLM_ANALYTICS):
            tag_queries(ai_query_source="dedicated_table")
            query_result = self.paginator.execute_hogql_query(
                query=query,
                placeholders={"filter_conditions": rewrite_expr_for_ai_events_table(self._get_session_filter())},
                team=self.team,
                user=self.user,
                query_type=NodeKind.SESSION_QUERY,
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
            )

        if not query_result.results:
            fallback_filter = self._get_events_fallback_filter()
            if fallback_filter is None:
                return self._response_from_query_result(query_result, [])

            with (
                self.timings.measure("session_query_events_fallback_execute"),
                tags_context(product=Product.LLM_ANALYTICS),
            ):
                tag_queries(ai_query_source="shared_table_fallback")
                query_result = self.paginator.execute_hogql_query(
                    query=rewrite_query_for_events_table(query, self.team.pk),
                    placeholders={"filter_conditions": rewrite_expr_for_events_table(fallback_filter, self.team.pk)},
                    team=self.team,
                    user=self.user,
                    query_type="SessionQueryEventsFallback",
                    timings=self.timings,
                    modifiers=self.modifiers,
                    limit_context=self.limit_context,
                )
                query_result.columns = restore_events_result_alias(query_result.columns)

        columns: list[str] = query_result.columns or []
        results = self.paginator.results
        sentiment_lookup = EMPTY_SENTIMENT_EVALUATION_LOOKUP
        if self.query.includeSentiment and results and columns:
            sentiment_lookup = load_generation_sentiment_evaluations_for_traces(
                team=self.team,
                trace_ids=self._trace_ids_from_results(columns, results),
                timings=self.timings,
                modifiers=self.modifiers,
                limit_context=self.limit_context,
                query_type="SessionQuerySentimentEvaluations",
            )

        return self._response_from_query_result(query_result, self._map_results(columns, results, sentiment_lookup))

    def to_query(self) -> ast.SelectQuery:
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
                        WHEN countIf(latency > 0 AND event != '$ai_generation') = 0
                             AND countIf(latency > 0 AND event = '$ai_generation') > 0
                        THEN sumIf(latency,
                                   event = '$ai_generation' AND latency > 0
                             )
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
                    sumIf(request_cost_usd,
                          event IN ('$ai_generation', '$ai_embedding')
                    ), 10
                ), 0) AS request_cost,
                nullIf(round(
                    sumIf(web_search_cost_usd,
                          event IN ('$ai_generation', '$ai_embedding')
                    ), 10
                ), 0) AS web_search_cost,
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
                ) AS trace_name,
                countIf(is_error = 1 OR isNotNull(error)) AS error_count,
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
            FROM posthog.ai_events AS ai_events
            WHERE event IN (
                '$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace'
            )
              AND {filter_conditions}
            GROUP BY trace_id
            ORDER BY first_timestamp DESC
            """,
        )
        return cast(ast.SelectQuery, query)

    def get_cache_payload(self) -> dict[str, Any]:
        return {
            **super().get_cache_payload(),
            "schema_version": 1,
        }

    def cache_target_age(self, last_refresh: Optional[datetime], lazy: bool = False) -> Optional[datetime]:
        if last_refresh is None:
            return None

        return last_refresh + timedelta(minutes=1)

    @cached_property
    def _date_range(self) -> QueryDateRange:
        return QueryDateRange(self.query.dateRange, self.team, IntervalType.MINUTE, datetime.now())

    def _has_fallback_date_range(self) -> bool:
        return bool(self.query.dateRange and self.query.dateRange.date_from)

    def _get_session_filter(self) -> ast.Expr:
        return ast.And(
            exprs=[
                ast.Call(name="isNotNull", args=[ast.Field(chain=["ai_events", "trace_id"])]),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotEq,
                    left=ast.Field(chain=["ai_events", "trace_id"]),
                    right=ast.Constant(value=""),
                ),
                ast.Call(name="isNotNull", args=[ast.Field(chain=["ai_events", "session_id"])]),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["ai_events", "session_id"]),
                    right=ast.Constant(value=self.query.sessionId),
                ),
            ]
        )

    def _get_events_fallback_filter(self) -> ast.Expr | None:
        if not self._has_fallback_date_range():
            return None

        return ast.And(
            exprs=[
                self._get_session_filter(),
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
        )

    def _response_from_query_result(self, query_result: Any, results: list[LLMTrace]) -> SessionQueryResponse:
        return SessionQueryResponse(
            columns=query_result.columns or [],
            results=results,
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    def _trace_ids_from_results(self, columns: list[str], query_results: list) -> list[str]:
        if "id" not in columns:
            return []

        id_index = columns.index("id")
        return [str(row[id_index]) for row in query_results if row and row[id_index]]

    def _map_event(self, event_tuple: tuple, sentiment_lookup: SentimentEvaluationLookup) -> LLMTraceEvent:
        event_uuid, event_name, event_timestamp, event_properties, *heavy = event_tuple
        heavy_columns = dict(zip(("input", "output", "output_choices", "input_state", "output_state", "tools"), heavy))
        event_id = str(event_uuid)
        properties = merge_heavy_properties(event_properties, heavy_columns)
        event_data: dict[str, Any] = {
            "id": event_id,
            "event": event_name,
            "createdAt": event_timestamp.isoformat(),
            "properties": properties,
        }
        sentiment_lookup_ids = get_generation_sentiment_lookup_ids(event_id, event_name, properties)
        sentiment = get_sentiment_for_generation(sentiment_lookup, sentiment_lookup_ids)
        if sentiment is not None:
            event_data["sentiment"] = sentiment

        return LLMTraceEvent.model_validate(event_data)

    def _map_trace(
        self, result: dict[str, Any], created_at: datetime, sentiment_lookup: SentimentEvaluationLookup
    ) -> LLMTrace:
        events = [self._map_event(event_tuple, sentiment_lookup) for event_tuple in result["events"]]

        trace_dict = {
            **result,
            "created_at": created_at.isoformat(),
            "events": events,
        }
        sentiment = sentiment_lookup.by_trace_id.get(str(result["id"]))
        if sentiment is not None:
            trace_dict["sentiment"] = sentiment

        for raw_key, parsed_key in [("input_state", "input_state_parsed"), ("output_state", "output_state_parsed")]:
            raw = trace_dict.get(raw_key) or None
            trace_dict[raw_key] = raw
            if raw is not None:
                try:
                    trace_dict[parsed_key] = orjson.loads(raw)
                except (TypeError, orjson.JSONDecodeError):
                    trace_dict[parsed_key] = raw

        return LLMTrace.model_validate(
            {
                SESSION_TRACE_FIELDS_MAPPING[key]: value
                for key, value in trace_dict.items()
                if key in SESSION_TRACE_FIELDS_MAPPING
            }
        )

    def _map_results(
        self, columns: list[str], query_results: list, sentiment_lookup: SentimentEvaluationLookup
    ) -> list[LLMTrace]:
        mapped_results = [dict(zip(columns, value)) for value in query_results]
        traces = []

        for result in mapped_results:
            traces.append(self._map_trace(result, cast(datetime, result["first_timestamp"]), sentiment_lookup))

        return traces
