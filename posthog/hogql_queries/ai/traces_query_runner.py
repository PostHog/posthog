from datetime import datetime
from typing import cast
from uuid import UUID

import orjson
import structlog

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import (
    AIGeneration,
    AITrace,
    AITracePerson,
    CachedTracesQueryResponse,
    NodeKind,
    TracesQuery,
    TracesQueryResponse,
)

logger = structlog.get_logger(__name__)


"""
select
    properties.$ai_trace_id as trace_id,
    min(timestamp) as trace_timestamp,
    max(person.properties) as person,
    sum(properties.$ai_latency) as total_latency,
    sum(properties.$ai_input_tokens) as input_tokens,
    sum(properties.$ai_output_tokens) as output_tokens,
    sum(properties.$ai_input_cost_usd) as input_cost,
    sum(properties.$ai_output_cost_usd) as output_cost,
    sum(properties.$ai_total_cost_usd) as total_cost,
    arraySort(x -> x.1, groupArray(tuple(timestamp, properties))) as events
from events
where
    event = '$ai_generation'
group by
    trace_id
order by
    trace_timestamp desc
"""


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
        return ast.SelectQuery(
            select=self._get_select_fields(),
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=self._get_where_clause(),
            order_by=self._get_order_by_clause(),
            group_by=[ast.Field(chain=["id"])],
        )

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

    def _map_results(self, columns: list[str], query_results: list):
        TRACE_FIELDS = {
            "id",
            "created_at",
            "person",
            "total_latency",
            "input_tokens",
            "output_tokens",
            "input_cost",
            "output_cost",
            "total_cost",
            "events",
        }
        mapped_results = [dict(zip(columns, value)) for value in query_results]
        traces = []

        for result in mapped_results:
            generations = []
            for uuid, timestamp, properties in result["events"]:
                generations.append(self._map_generation(uuid, timestamp, properties))
            trace_dict = {
                **result,
                "created_at": cast(datetime, result["trace_timestamp"]).isoformat(),
                "person": self._map_person(result["person"]),
                "events": generations,
            }
            trace = AITrace.model_validate({key: value for key, value in trace_dict.items() if key in TRACE_FIELDS})
            traces.append(trace)

        return traces

    def _map_generation(self, event_uuid: UUID, event_timestamp: datetime, event_properties: str) -> AIGeneration:
        properties: dict = orjson.loads(event_properties)

        GENERATION_MAPPING = {
            "$ai_input": "input",
            "$ai_latency": "latency",
            "$ai_output": "output",
            "$ai_provider": "provider",
            "$ai_model": "model",
            "$ai_input_tokens": "input_tokens",
            "$ai_output_tokens": "output_tokens",
            "$ai_input_cost_usd": "input_cost",
            "$ai_output_cost_usd": "output_cost",
            "$ai_total_cost_usd": "total_cost",
            "$ai_http_status": "http_status",
            "$ai_base_url": "base_url",
        }
        GENERATION_JSON_FIELDS = {"$ai_input", "$ai_output"}

        generation = {
            "id": str(event_uuid),
            "created_at": event_timestamp.isoformat(),
        }

        for event_prop, model_prop in GENERATION_MAPPING.items():
            if event_prop in properties:
                if event_prop in GENERATION_JSON_FIELDS:
                    generation[model_prop] = orjson.loads(properties[event_prop])
                else:
                    generation[model_prop] = properties[event_prop]

        return AIGeneration.model_validate(generation)

    def _map_person(self, person: tuple[UUID, UUID, datetime, str]) -> AITracePerson:
        uuid, distinct_id, created_at, properties = person
        return AITracePerson(
            uuid=str(uuid),
            distinct_id=str(distinct_id),
            created_at=created_at.isoformat(),
            properties=orjson.loads(properties),
        )

    def _get_select_fields(self) -> list[ast.Expr]:
        return [
            ast.Alias(expr=ast.Field(chain=["properties", "$ai_trace_id"]), alias="id"),
            ast.Alias(expr=ast.Call(name="min", args=[ast.Field(chain=["timestamp"])]), alias="trace_timestamp"),
            self._get_person_field(),
            ast.Alias(
                expr=ast.Call(name="sum", args=[ast.Field(chain=["properties", "$ai_latency"])]),
                alias="total_latency",
            ),
            ast.Alias(
                expr=ast.Call(name="sum", args=[ast.Field(chain=["properties", "$ai_input_tokens"])]),
                alias="input_tokens",
            ),
            ast.Alias(
                expr=ast.Call(name="sum", args=[ast.Field(chain=["properties", "$ai_output_tokens"])]),
                alias="output_tokens",
            ),
            ast.Alias(
                expr=ast.Call(name="sum", args=[ast.Field(chain=["properties", "$ai_input_cost_usd"])]),
                alias="input_cost",
            ),
            ast.Alias(
                expr=ast.Call(name="sum", args=[ast.Field(chain=["properties", "$ai_output_cost_usd"])]),
                alias="output_cost",
            ),
            ast.Alias(
                expr=ast.Call(name="sum", args=[ast.Field(chain=["properties", "$ai_total_cost_usd"])]),
                alias="total_cost",
            ),
            ast.Alias(
                expr=ast.Call(
                    name="arraySort",
                    args=[
                        ast.Lambda(
                            args=["x"],
                            expr=ast.Call(name="tupleElement", args=[ast.Field(chain=["x"]), ast.Constant(value=2)]),
                        ),
                        ast.Call(
                            name="groupArray",
                            args=[
                                ast.Tuple(
                                    exprs=[
                                        ast.Field(chain=["uuid"]),
                                        ast.Field(chain=["timestamp"]),
                                        ast.Field(chain=["properties"]),
                                    ]
                                )
                            ],
                        ),
                    ],
                ),
                alias="events",
            ),
        ]

    def _get_person_field(self):
        return ast.Alias(
            expr=ast.Tuple(
                exprs=[
                    ast.Call(name="max", args=[ast.Field(chain=["person", "id"])]),
                    ast.Call(name="max", args=[ast.Field(chain=["distinct_id"])]),
                    ast.Call(name="max", args=[ast.Field(chain=["person", "created_at"])]),
                    ast.Call(name="max", args=[ast.Field(chain=["person", "properties"])]),
                ],
            ),
            alias="person",
        )

    def _get_where_clause(self):
        event_expr = ast.CompareOperation(
            left=ast.Field(chain=["event"]),
            op=ast.CompareOperationOp.Eq,
            right=ast.Constant(value="$ai_generation"),
        )
        if self.query.traceId is not None:
            return ast.And(
                exprs=[
                    event_expr,
                    ast.CompareOperation(
                        left=ast.Field(chain=["id"]),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Constant(value=self.query.traceId),
                    ),
                ]
            )
        return event_expr

    def _get_order_by_clause(self):
        return [ast.OrderExpr(expr=ast.Field(chain=["trace_timestamp"]), order="DESC")]
