from datetime import datetime, timedelta
from functools import cached_property
from typing import Any, cast
from uuid import UUID

import orjson
import structlog

from posthog.schema import (
    CachedTracesQueryResponse,
    IntervalType,
    LLMTrace,
    LLMTraceEvent,
    LLMTracePerson,
    NodeKind,
    TracesQuery,
    TracesQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

logger = structlog.get_logger(__name__)


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


class TracesQueryRunner(AnalyticsQueryRunner[TracesQueryResponse]):
    query: TracesQuery
    cached_response: CachedTracesQueryResponse
    paginator: HogQLHasMorePaginator

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset,
        )

    def _calculate(self):
        with self.timings.measure("traces_query_hogql_execute"):
            # Calculate max number of events needed with current offset and limit
            limit_value = self.query.limit if self.query.limit else 100
            offset_value = self.query.offset if self.query.offset else 0
            pagination_limit = limit_value + offset_value + 1

            query_result = self.paginator.execute_hogql_query(
                query=self.to_query(),
                placeholders={
                    "subquery_conditions": self._get_subquery_filter(),
                    "filter_conditions": self._get_where_clause(),
                    "pagination_limit": ast.Constant(value=pagination_limit),
                },
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

    def to_query(self):
        query = parse_select(
            """
            WITH relevant_trace_ids AS (
                SELECT properties.$ai_trace_id as trace_id
                FROM events
                WHERE event IN ('$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace')
                  AND {subquery_conditions}
                ORDER BY timestamp DESC
                LIMIT 1 BY properties.$ai_trace_id
                LIMIT {pagination_limit}
            )
            SELECT
                properties.$ai_trace_id AS id,
                min(timestamp) AS first_timestamp,
                tuple(
                    argMin(person.id, timestamp),
                    argMin(distinct_id, timestamp),
                    argMin(person.created_at, timestamp),
                    argMin(person.properties, timestamp)
                ) AS first_person,
                round(
                    CASE
                        -- If all events with latency are generations, sum them all
                        WHEN countIf(toFloat(properties.$ai_latency) > 0 AND event != '$ai_generation') = 0
                             AND countIf(toFloat(properties.$ai_latency) > 0 AND event = '$ai_generation') > 0
                        THEN sumIf(toFloat(properties.$ai_latency),
                                   event = '$ai_generation' AND toFloat(properties.$ai_latency) > 0
                             )
                        -- Otherwise sum the direct children of the trace
                        ELSE sumIf(toFloat(properties.$ai_latency),
                                   properties.$ai_parent_id IS NULL
                                   OR toString(properties.$ai_parent_id) = toString(properties.$ai_trace_id)
                             )
                    END, 2
                ) AS total_latency,
                sumIf(toFloat(properties.$ai_input_tokens),
                      event IN ('$ai_generation', '$ai_embedding')
                ) AS input_tokens,
                sumIf(toFloat(properties.$ai_output_tokens),
                      event IN ('$ai_generation', '$ai_embedding')
                ) AS output_tokens,
                round(
                    sumIf(toFloat(properties.$ai_input_cost_usd),
                          event IN ('$ai_generation', '$ai_embedding')
                    ), 4
                ) AS input_cost,
                round(
                    sumIf(toFloat(properties.$ai_output_cost_usd),
                          event IN ('$ai_generation', '$ai_embedding')
                    ), 4
                ) AS output_cost,
                round(
                    sumIf(toFloat(properties.$ai_total_cost_usd),
                          event IN ('$ai_generation', '$ai_embedding')
                    ), 4
                ) AS total_cost,
                arrayDistinct(
                    arraySort(x -> x.3,
                        groupArrayIf(
                            tuple(uuid, event, timestamp, properties),
                            event IN ('$ai_metric', '$ai_feedback') OR toString(properties.$ai_parent_id) = toString(properties.$ai_trace_id)
                        )
                    )
                ) AS events,
                argMinIf(properties.$ai_input_state,
                         timestamp, event = '$ai_trace'
                ) AS input_state,
                argMinIf(properties.$ai_output_state,
                         timestamp, event = '$ai_trace'
                ) AS output_state,
                ifNull(
                    argMinIf(
                        ifNull(properties.$ai_span_name, properties.$ai_trace_name),
                        timestamp,
                        event = '$ai_trace'
                    ),
                    argMin(
                        ifNull(properties.$ai_span_name, properties.$ai_trace_name),
                        timestamp,
                    )
                ) AS trace_name
            FROM events
            WHERE event IN (
                '$ai_span', '$ai_generation', '$ai_embedding', '$ai_metric', '$ai_feedback', '$ai_trace'
            )
              AND properties.$ai_trace_id IN (SELECT trace_id FROM relevant_trace_ids)
              AND {filter_conditions}
            GROUP BY properties.$ai_trace_id
            ORDER BY first_timestamp DESC
            """,
        )
        return cast(ast.SelectQuery, query)

    def get_cache_payload(self):
        return {
            **super().get_cache_payload(),
            # When the response schema changes, increment this version to invalidate the cache.
            "schema_version": 2,
        }

    @cached_property
    def _date_range(self):
        # Minute-level precision for 10m capture range
        return TracesQueryDateRange(self.query.dateRange, self.team, IntervalType.MINUTE, datetime.now())

    def _map_results(self, columns: list[str], query_results: list):
        mapped_results = [dict(zip(columns, value)) for value in query_results]
        traces = []

        for result in mapped_results:
            # Exclude traces that are outside of the capture range.
            timestamp_dt = cast(datetime, result["first_timestamp"])
            if (
                timestamp_dt < self._date_range.date_from_for_filtering()
                or timestamp_dt > self._date_range.date_to_for_filtering()
            ):
                continue

            traces.append(self._map_trace(result, timestamp_dt))

        return traces

    def _map_trace(self, result: dict[str, Any], created_at: datetime) -> LLMTrace:
        TRACE_FIELDS_MAPPING = {
            "id": "id",
            "created_at": "createdAt",
            "person": "person",
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

        generations = []
        for uuid, event_name, timestamp, properties in result["events"]:
            generations.append(self._map_event(uuid, event_name, timestamp, properties))

        trace_dict = {
            **result,
            "created_at": created_at.isoformat(),
            "person": self._map_person(result["first_person"]),
            "events": generations,
        }
        try:
            trace_dict["input_state_parsed"] = orjson.loads(trace_dict["input_state"])
        except (TypeError, orjson.JSONDecodeError):
            pass
        try:
            trace_dict["output_state_parsed"] = orjson.loads(trace_dict["output_state"])
        except (TypeError, orjson.JSONDecodeError):
            pass
        # Remap keys from snake case to camel case
        trace = LLMTrace.model_validate(
            {TRACE_FIELDS_MAPPING[key]: value for key, value in trace_dict.items() if key in TRACE_FIELDS_MAPPING}
        )
        return trace

    def _map_event(
        self, event_uuid: UUID, event_name: str, event_timestamp: datetime, event_properties: str
    ) -> LLMTraceEvent:
        generation: dict[str, Any] = {
            "id": str(event_uuid),
            "event": event_name,
            "createdAt": event_timestamp.isoformat(),
            "properties": orjson.loads(event_properties),
        }
        return LLMTraceEvent.model_validate(generation)

    def _map_person(self, person: tuple[UUID, UUID, datetime, str]) -> LLMTracePerson:
        uuid, distinct_id, created_at, properties = person
        return LLMTracePerson(
            uuid=str(uuid),
            distinct_id=str(distinct_id),
            created_at=created_at.isoformat(),
            properties=orjson.loads(properties) if properties else {},
        )

    def _get_subquery_filter(self) -> ast.Expr:
        exprs: list[ast.Expr] = [
            ast.Call(name="isNotNull", args=[ast.Field(chain=["properties", "$ai_trace_id"])]),
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

    def _get_where_clause(self) -> ast.Expr:
        where_exprs: list[ast.Expr] = [
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

        if self.query.filterTestAccounts:
            with self.timings.measure("test_account_filters"):
                for prop in self.team.test_account_filters or []:
                    where_exprs.append(property_to_expr(prop, self.team))

        return ast.And(exprs=where_exprs)

    def _get_order_by_clause(self):
        return [ast.OrderExpr(expr=ast.Field(chain=["trace_timestamp"]), order="DESC")]
