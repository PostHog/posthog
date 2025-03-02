import json

from posthog.hogql import ast
from posthog.hogql.ast import CompareOperationOp
from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.hogql_queries.utils.revenue import revenue_expression, revenue_events_expr
from posthog.schema import (
    RevenueExampleEventsQuery,
    RevenueExampleEventsQueryResponse,
    CachedRevenueExampleEventsQueryResponse,
)


class RevenueExampleEventsQueryRunner(QueryRunner):
    query: RevenueExampleEventsQuery
    response: RevenueExampleEventsQueryResponse
    cached_response: CachedRevenueExampleEventsQueryResponse
    paginator: HogQLHasMorePaginator

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY, limit=self.query.limit if self.query.limit else None
        )

    def to_query(self) -> ast.SelectQuery:
        tracking_config = self.query.revenueTrackingConfig

        select = ast.SelectQuery(
            select=[
                ast.Call(
                    name="tuple",
                    args=[
                        ast.Field(chain=["uuid"]),
                        ast.Field(chain=["event"]),
                        ast.Field(chain=["distinct_id"]),
                        ast.Field(chain=["properties"]),
                    ],
                ),
                ast.Field(chain=["event"]),
                ast.Alias(alias="revenue", expr=revenue_expression(tracking_config)),
                ast.Call(
                    name="tuple",
                    args=[
                        ast.Field(chain=["person", "id"]),
                        ast.Field(chain=["person", "created_at"]),
                        ast.Field(chain=["distinct_id"]),
                        ast.Field(chain=["person", "properties"]),
                    ],
                ),
                ast.Alias(alias="session_id", expr=ast.Field(chain=["properties", "$session_id"])),
                ast.Field(chain=["timestamp"]),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    revenue_events_expr(tracking_config),
                    ast.CompareOperation(
                        op=CompareOperationOp.NotEq,
                        left=revenue_expression(tracking_config),
                        right=ast.Constant(value=None),
                    ),
                ]
            ),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
        )

        return select

    def calculate(self):
        response = self.paginator.execute_hogql_query(
            query_type="revenue_example_events_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )

        results = [
            (
                {
                    "uuid": row[0][0],
                    "event": row[0][1],
                    "distinct_id": row[0][2],
                    "properties": json.loads(row[0][3]),
                },
                row[1],
                row[2],
                {
                    "id": row[3][0],
                    "created_at": row[3][1],
                    "distinct_id": row[3][2],
                    "properties": json.loads(row[3][3]),
                },
                row[4],
                row[5],
            )
            for row in response.results
        ]

        return RevenueExampleEventsQueryResponse(
            columns=[
                "*",
                "event",
                "revenue",
                "person",
                "timestamp",
                "session_id",
            ],
            results=results,
            timings=response.timings,
            types=response.types,
            hogql=response.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )
