from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import (
    HogQLFilters,
    ErrorTrackingQuery,
    ErrorTrackingQueryResponse,
    CachedErrorTrackingQueryResponse,
)
from posthog.hogql.parser import parse_expr


class ErrorTrackingQueryRunner(QueryRunner):
    query: ErrorTrackingQuery
    response: ErrorTrackingQueryResponse
    paginator: HogQLHasMorePaginator
    cached_response: CachedErrorTrackingQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY,
            limit=self.query.limit if self.query.limit else None,
            offset=self.query.offset if self.query.offset else None,
        )

    def to_query(self) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=[parse_expr(x) for x in self.query.select],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=self._where(),
            order_by=self._order_by(),
            group_by=[ast.Field(chain=["events", "properties", "$exception_fingerprint"])],
        )

    def _where(self):
        where_exprs: list[ast.Expr] = [
            ast.CompareOperation(
                op=ast.CompareOperationOp.Eq,
                left=ast.Field(chain=["event"]),
                right=ast.Constant(value="$exception"),
            ),
            ast.Placeholder(field="filters"),
        ]

        if self.query.fingerprint:
            where_exprs.append(
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=["properties", "$exception_fingerprint"]),
                    right=ast.Constant(value=self.query.fingerprint),
                )
            )

        return ast.And(exprs=where_exprs)

    def _order_by(self):
        return (
            [
                ast.OrderExpr(
                    expr=ast.Field(chain=[self.query.order]),
                    order="ASC" if self.query.order == "first_seen" else "DESC",
                )
            ]
            if self.query.order
            else None
        )

    def calculate(self):
        properties = self.query.filterGroup.values[0].values if self.query.filterGroup else None

        query_result = self.paginator.execute_hogql_query(
            query=self.to_query(),
            team=self.team,
            query_type="ErrorTrackingQuery",
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
            filters=HogQLFilters(
                dateRange=self.query.dateRange,
                filterTestAccounts=self.query.filterTestAccounts,
                properties=properties,
            ),
        )

        return ErrorTrackingQueryResponse(
            columns=query_result.columns,
            results=query_result.results,
            timings=query_result.timings,
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )
