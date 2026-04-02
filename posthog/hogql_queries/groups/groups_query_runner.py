from posthog.schema import CachedGroupsQueryResponse, GroupsQuery, GroupsQueryResponse

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.parser import parse_expr, parse_order_expr
from posthog.hogql.property import has_aggregation, property_to_expr

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner


class GroupsQueryRunner(AnalyticsQueryRunner[GroupsQueryResponse]):
    query: GroupsQuery
    cached_response: CachedGroupsQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.query.group_type_index is None:
            raise ValueError("group_type_index is required")

        # Detect if this is a count/aggregation query
        self.is_aggregation_query = False
        if self.query.select:
            self.is_aggregation_query = any(has_aggregation(parse_expr(col)) for col in self.query.select)

        # Handle column logic differently for aggregation queries
        if self.is_aggregation_query:
            # For aggregation queries, use select as-is (e.g., ['count(*)'])
            self.columns = self.query.select or []
        elif self.query.select:
            seen: set[str] = set()
            self.columns = []
            for col in self.query.select:
                if col not in seen:
                    seen.add(col)
                    self.columns.append(col)
        else:
            self.columns = ["group_name"]

        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=self.limit_context, limit=self.query.limit, offset=self.query.offset
        )

    def to_query(self) -> ast.SelectQuery:
        where_exprs: list[ast.Expr] = []

        where_exprs.append(
            ast.CompareOperation(
                left=ast.Field(chain=["index"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=self.query.group_type_index),
            )
        )

        if self.query.properties:
            where_exprs.append(property_to_expr(self.query.properties, self.team, scope="group"))

        # Search logic for both aggregation and regular queries
        if self.query.search is not None and self.query.search != "":
            where_exprs.append(
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

        where = ast.And(exprs=list(where_exprs)) if where_exprs else None

        order_by: list[ast.OrderExpr] = []

        if self.is_aggregation_query:
            select_exprs = [parse_expr(col) for col in self.columns]

            return ast.SelectQuery(
                select=select_exprs,
                select_from=ast.JoinExpr(table=ast.Field(chain=["groups"])),
                where=where,
                order_by=order_by,
            )
        else:
            similarity_order = None

            if self.query.search is not None and self.query.search != "":
                similarity_order = self._get_similarity_order_for_search()

            order_by_exprs = self.query.orderBy if self.query.orderBy else ["created_at DESC"]
            has_user_ordering = self.query.orderBy is not None and len(self.query.orderBy) > 0

            # Add user-specified ordering first
            for col in order_by_exprs:
                # group_name isn't actually a field
                if col.startswith("group_name"):
                    order_by.append(
                        ast.OrderExpr(
                            expr=ast.Call(
                                name="coalesce",
                                args=[ast.Field(chain=["properties", "name"]), ast.Field(chain=["key"])],
                            ),
                            order="DESC" if "DESC" in col else "ASC",
                        )
                    )
                else:
                    order_by.append(parse_order_expr(col, timings=self.timings))

            if similarity_order is not None:
                # Add similarity ordering after user ordering (but not after default created_at DESC)
                order_by.append(similarity_order) if has_user_ordering else order_by.insert(0, similarity_order)

            return ast.SelectQuery(
                select=[self._column_to_expr(col) for col in self.columns],
                select_from=ast.JoinExpr(table=ast.Field(chain=["groups"])),
                where=where,
                order_by=order_by,
            )

    def _column_to_expr(self, col: str) -> ast.Expr:
        if col == "group_name":
            return ast.Call(
                name="tuple",
                args=[
                    ast.Call(name="coalesce", args=[ast.Field(chain=["properties", "name"]), ast.Field(chain=["key"])]),
                    ast.Call(name="toString", args=[ast.Field(chain=["key"])]),
                ],
            )
        return parse_expr(col)

    def _calculate(self) -> GroupsQueryResponse:
        response = self.paginator.execute_hogql_query(
            query_type="GroupsQuery",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            # :HACKY: posthog/hogql/transforms/property_types.py needs access to the group_id in order to know the property type
            context=HogQLContext(team_id=self.team.pk, globals={"group_id": self.query.group_type_index}),
        )
        results = response.results[: self.paginator.limit] if self.paginator.limit is not None else response.results

        if "group_name" in self.columns:
            column_index = self.columns.index("group_name")
            results = [
                [
                    {"display_name": col[0], "key": str(col[1])} if index == column_index else col
                    for index, col in enumerate(row)
                ]
                for row in results
            ]

        return GroupsQueryResponse(
            kind="GroupsQuery",
            types=[t for _, t in response.types] if response.types else None,
            columns=self.columns,
            results=results,
            hogql=response.hogql,
            **self.paginator.response_params(),
        )

    def _get_similarity_order_for_search(self) -> ast.OrderExpr:
        """
        When a search term exists, we want to rank the results by how close they are to it.
        """
        display_name_expr = ast.Call(
            name="coalesce", args=[ast.Field(chain=["properties", "name"]), ast.Field(chain=["key"])]
        )

        return ast.OrderExpr(
            expr=ast.Call(
                name="multiIf",
                args=[
                    # Exact match = 0 (highest priority)
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.ILike,
                        left=display_name_expr,
                        right=ast.Constant(value=self.query.search),
                    ),
                    ast.Constant(value=0),
                    # Starts with search term = 1
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.ILike,
                        left=display_name_expr,
                        right=ast.Constant(value=f"{self.query.search}%"),
                    ),
                    ast.Constant(value=1),
                    # Contains search term = 2 (lowest priority)
                    ast.Constant(value=2),
                ],
            ),
            order="ASC",
        )
