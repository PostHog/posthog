from posthog.hogql import ast
from posthog.hogql.parser import parse_order_expr
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner
from posthog.schema import GroupsQuery, GroupsQueryResponse, CachedGroupsQueryResponse


class GroupsQueryRunner(QueryRunner):
    query: GroupsQuery
    response: GroupsQueryResponse
    cached_response: CachedGroupsQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.query.group_type_index is None:
            raise ValueError("group_type_index is required")

        self.columns = [
            "group_name",
            "key",
        ]
        if self.query.select:
            self.columns.extend([col for col in self.query.select if col not in self.columns])

        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=self.limit_context, limit=self.query.limit, offset=self.query.offset
        )

    def to_query(self) -> ast.SelectQuery:
        conditions = []

        conditions.append(
            ast.CompareOperation(
                left=ast.Field(chain=["index"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=self.query.group_type_index),
            )
        )

        if self.query.search is not None and self.query.search != "":
            conditions.append(
                ast.Or(
                    exprs=[
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.ILike,
                            left=ast.Field(chain=["properties", "name"]),
                            right=ast.Constant(value=f"%{self.query.search}%"),
                        ),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.ILike,
                            left=ast.Call(name="toString", args=[ast.Field(chain=["key"])]),
                            right=ast.Constant(value=f"%{self.query.search}%"),
                        ),
                    ]
                )
            )

        where = ast.And(exprs=list(conditions)) if conditions else None

        order_by: list[ast.OrderExpr] = []
        order_by_exprs = self.query.orderBy if self.query.orderBy else ["created_at DESC"]
        for col in order_by_exprs:
            # group_name isn't actually a field
            if col.startswith("group_name"):
                order_by.append(
                    ast.OrderExpr(
                        expr=ast.Call(
                            name="coalesce", args=[ast.Field(chain=["properties", "name"]), ast.Field(chain=["key"])]
                        ),
                        order="DESC" if "DESC" in col else "ASC",
                    )
                )
            else:
                order_by.append(parse_order_expr(col, timings=self.timings))

        return ast.SelectQuery(
            select=[
                ast.Call(name="coalesce", args=[ast.Field(chain=["properties", "name"]), ast.Field(chain=["key"])]),
                *[ast.Field(chain=list(col.split("."))) for col in self.columns[1:]],
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["groups"])),
            where=where,
            order_by=order_by,
        )

    def calculate(self) -> GroupsQueryResponse:
        response = self.paginator.execute_hogql_query(
            query_type="GroupsQuery",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )
        return GroupsQueryResponse(
            kind="GroupsQuery",
            types=[t for _, t in response.types] if response.types else None,
            columns=self.columns,
            results=response.results,
            hogql=response.hogql,
            **self.paginator.response_params(),
        )
