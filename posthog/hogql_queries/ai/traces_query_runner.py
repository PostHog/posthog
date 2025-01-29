from datetime import datetime, timedelta
from functools import cached_property
from typing import Any, cast
from uuid import UUID

import orjson
import structlog

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.parser import parse_select
from posthog.hogql.property import property_to_expr
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
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


class TracesQueryRunner(QueryRunner):
    query: TracesQuery
    response: TracesQueryResponse
    cached_response: CachedTracesQueryResponse
    paginator: HogQLHasMorePaginator

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset,
        )

    def to_query(self) -> ast.SelectQuery:
        query = self._get_event_query()
        if self.query.properties:
            query.having = ast.CompareOperation(
                left=ast.Field(chain=["filter_match"]), op=ast.CompareOperationOp.Eq, right=ast.Constant(value=1)
            )
        return query

    def calculate(self):
        with self.timings.measure("traces_query_hogql_execute"):
            query_result = self.paginator.execute_hogql_query(
                query=self.to_query(),
                placeholders={
                    "common_conditions": self._get_where_clause(),
                    "filter_conditions": self._get_properties_filter(),
                    "return_full_trace": ast.Constant(value=1 if self.query.traceId is not None else 0),
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

    def _get_event_query(self) -> ast.SelectQuery:
        query = parse_select(
            """
            SELECT
                generations.id AS id,
                generations.first_timestamp AS first_timestamp,
                generations.first_person AS first_person,
                generations.total_latency AS total_latency,
                generations.input_tokens AS input_tokens,
                generations.output_tokens AS output_tokens,
                generations.input_cost AS input_cost,
                generations.output_cost AS output_cost,
                generations.total_cost AS total_cost,
                if({return_full_trace}, generations.events, arrayFilter(x -> x.2 IN ('$ai_metric', '$ai_feedback'), generations.events)) as events,
                traces.input_state AS input_state,
                traces.output_state AS output_state,
                traces.trace_name AS trace_name,
                generations.filter_match OR traces.filter_match AS filter_match
            FROM (
                SELECT
                    properties.$ai_trace_id as id,
                    min(timestamp) as first_timestamp,
                    tuple(
                        argMin(person.id, timestamp), argMin(distinct_id, timestamp),
                        argMin(person.created_at, timestamp), argMin(person.properties, timestamp)
                    ) as first_person,
                    round(toFloat(sum(properties.$ai_latency)), 2) as total_latency,
                    sum(properties.$ai_input_tokens) as input_tokens,
                    sum(properties.$ai_output_tokens) as output_tokens,
                    round(sum(toFloat(properties.$ai_input_cost_usd)), 4) as input_cost,
                    round(sum(toFloat(properties.$ai_output_cost_usd)), 4) as output_cost,
                    round(sum(toFloat(properties.$ai_total_cost_usd)), 4) as total_cost,
                    arraySort(x -> x.3, groupArray(tuple(uuid, event, timestamp, properties))) as events,
                    {filter_conditions}
                FROM events
                WHERE event IN ('$ai_span', '$ai_generation', '$ai_metric', '$ai_feedback') AND {common_conditions}
                GROUP BY id
            ) AS generations
            LEFT JOIN (
                SELECT
                    properties.$ai_trace_id as id,
                    argMin(properties.$ai_input_state, timestamp) as input_state,
                    argMin(properties.$ai_output_state, timestamp) as output_state,
                    argMin(ifNull(properties.$ai_span_name, properties.$ai_trace_name), timestamp) as trace_name,
                    {filter_conditions}
                FROM events
                WHERE event = '$ai_trace' AND {common_conditions}
                GROUP BY id -- In case there are multiple trace events for the same trace ID, an unexpected but possible case
            ) AS traces
            ON traces.id = generations.id
            ORDER BY first_timestamp DESC
            """,
        )
        return cast(ast.SelectQuery, query)

    def _get_properties_filter(self):
        expr: ast.Expr = ast.Constant(value=1)
        if self.query.properties:
            with self.timings.measure("property_filters"):
                filter = ast.And(exprs=[property_to_expr(property, self.team) for property in self.query.properties])
                expr = ast.Call(name="max", args=[filter])
        return ast.Alias(alias="filter_match", expr=expr)

    def _get_where_clause(self):
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

        if self.query.traceId is not None:
            where_exprs.append(
                ast.CompareOperation(
                    left=ast.Field(chain=["id"]),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Constant(value=self.query.traceId),
                ),
            )

        return ast.And(exprs=where_exprs)

    def _get_order_by_clause(self):
        return [ast.OrderExpr(expr=ast.Field(chain=["trace_timestamp"]), order="DESC")]
