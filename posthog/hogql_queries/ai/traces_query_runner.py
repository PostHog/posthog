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
    LLMGeneration,
    LLMTrace,
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
        query.where = self._get_where_clause()
        return query

    def calculate(self):
        with self.timings.measure("traces_query_hogql_execute"):
            query_result = self.paginator.execute_hogql_query(
                query=self.to_query(),
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

    @cached_property
    def _date_range(self):
        # Minute-level precision for 10m capture range
        return TracesQueryDateRange(self.query.dateRange, self.team, IntervalType.MINUTE, datetime.now())

    def _map_results(self, columns: list[str], query_results: list):
        mapped_results = [dict(zip(columns, value)) for value in query_results]
        traces = []

        for result in mapped_results:
            # Exclude traces that are outside of the capture range.
            timestamp_dt = cast(datetime, result["trace_timestamp"])
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
            "input_tokens": "inputTokens",
            "output_tokens": "outputTokens",
            "input_cost": "inputCost",
            "output_cost": "outputCost",
            "total_cost": "totalCost",
            "events": "events",
        }

        generations = []
        for uuid, timestamp, properties in result["events"]:
            generations.append(self._map_generation(uuid, timestamp, properties))

        trace_dict = {
            **result,
            "created_at": created_at.isoformat(),
            "person": self._map_person(result["person"]),
            "events": generations,
        }
        # Remap keys from snake case to camel case
        trace = LLMTrace.model_validate(
            {TRACE_FIELDS_MAPPING[key]: value for key, value in trace_dict.items() if key in TRACE_FIELDS_MAPPING}
        )
        return trace

    def _map_generation(self, event_uuid: UUID, event_timestamp: datetime, event_properties: str) -> LLMGeneration:
        properties: dict = orjson.loads(event_properties)

        GENERATION_MAPPING = {
            "$ai_input": "input",
            "$ai_latency": "latency",
            "$ai_output": "output",
            "$ai_provider": "provider",
            "$ai_model": "model",
            "$ai_input_tokens": "inputTokens",
            "$ai_output_tokens": "outputTokens",
            "$ai_input_cost_usd": "inputCost",
            "$ai_output_cost_usd": "outputCost",
            "$ai_total_cost_usd": "totalCost",
            "$ai_http_status": "httpStatus",
            "$ai_base_url": "baseUrl",
        }
        GENERATION_JSON_FIELDS = {"$ai_input", "$ai_output"}

        generation: dict[str, Any] = {
            "id": str(event_uuid),
            "createdAt": event_timestamp.isoformat(),
        }

        for event_prop, model_prop in GENERATION_MAPPING.items():
            if event_prop in properties:
                if event_prop in GENERATION_JSON_FIELDS:
                    try:
                        generation[model_prop] = orjson.loads(properties[event_prop])
                    except orjson.JSONDecodeError:
                        if event_prop == "$ai_input":
                            generation[model_prop] = []
                else:
                    generation[model_prop] = properties[event_prop]

        return LLMGeneration.model_validate(generation)

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
                    properties.$ai_trace_id as id,
                    min(timestamp) as trace_timestamp,
                    tuple(max(person.id), max(distinct_id), max(person.created_at), max(person.properties)) as person,
                    round(toFloat(sum(properties.$ai_latency)), 2) as total_latency,
                    sum(properties.$ai_input_tokens) as input_tokens,
                    sum(properties.$ai_output_tokens) as output_tokens,
                    round(toFloat(sum(properties.$ai_input_cost_usd)), 4) as input_cost,
                    round(toFloat(sum(properties.$ai_output_cost_usd)), 4) as output_cost,
                    round(toFloat(sum(properties.$ai_total_cost_usd)), 4) as total_cost,
                    arraySort(x -> x.2, groupArray(tuple(uuid, timestamp, properties))) as events
                FROM
                    events
                GROUP BY
                    id
                ORDER BY
                    trace_timestamp DESC
            """
        )
        return cast(ast.SelectQuery, query)

    def _get_where_clause(self):
        timestamp_field = ast.Field(chain=["events", "timestamp"])

        exprs: list[ast.Expr] = [
            ast.CompareOperation(
                left=ast.Field(chain=["event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value="$ai_generation"),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.GtEq,
                left=timestamp_field,
                right=self._date_range.date_from_as_hogql(),
            ),
            ast.CompareOperation(
                op=ast.CompareOperationOp.LtEq,
                left=timestamp_field,
                right=self._date_range.date_to_as_hogql(),
            ),
        ]

        if self.query.filterTestAccounts:
            with self.timings.measure("test_account_filters"):
                for prop in self.team.test_account_filters or []:
                    exprs.append(property_to_expr(prop, self.team))

        if self.query.traceId is not None:
            exprs.append(
                ast.CompareOperation(
                    left=ast.Field(chain=["id"]),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Constant(value=self.query.traceId),
                ),
            )

        return ast.And(exprs=exprs)

    def _get_order_by_clause(self):
        return [ast.OrderExpr(expr=ast.Field(chain=["trace_timestamp"]), order="DESC")]
