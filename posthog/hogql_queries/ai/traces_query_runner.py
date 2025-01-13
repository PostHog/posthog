import structlog

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import (
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
    arraySort(x -> x.1, groupArray(tuple(timestamp, properties))) as spans
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
            group_by=[ast.Field(chain=["trace_id"])],
        )

    def calculate(self):
        with self.timings.measure("error_tracking_query_hogql_execute"):
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
        mapped_results = [dict(zip(columns, value)) for value in query_results]
        return mapped_results

    def _get_select_fields(self) -> list[ast.Expr]:
        return [
            ast.Field(chain=["properties", "$ai_trace_id"]),
            ast.Call(name="min", args=[ast.Field(chain=["timestamp"])]),
            ast.Call(name="max", args=[ast.Field(chain=["person", "properties"])]),
            ast.Call(name="sum", args=[ast.Field(chain=["properties", "$ai_latency"])]),
            ast.Call(name="sum", args=[ast.Field(chain=["properties", "$ai_input_tokens"])]),
            ast.Call(name="sum", args=[ast.Field(chain=["properties", "$ai_output_tokens"])]),
            ast.Call(name="sum", args=[ast.Field(chain=["properties", "$ai_input_cost_usd"])]),
            ast.Call(name="sum", args=[ast.Field(chain=["properties", "$ai_output_cost_usd"])]),
            ast.Call(name="sum", args=[ast.Field(chain=["properties", "$ai_total_cost_usd"])]),
            ast.Call(
                name="arraySort",
                args=[
                    ast.Lambda(args=["x"], expr=ast.Field(chain=["x", "1"])),
                    ast.Call(
                        name="groupArray",
                        args=[
                            ast.Tuple(
                                exprs=[
                                    ast.Field(chain=["timestamp"]),
                                    ast.Field(chain=["properties"]),
                                ]
                            )
                        ],
                    ),
                ],
            ),
        ]

    def _get_where_clause(self):
        return ast.CompareOperation(
            left=ast.Field(chain=["event"]),
            op=ast.CompareOperationOp.Eq,
            right=ast.Constant(value="$ai_generation"),
        )

    def _get_order_by_clause(self):
        return [ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")]
