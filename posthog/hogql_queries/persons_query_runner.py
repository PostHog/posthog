from typing import Optional, Any, Dict, List

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.models import Team
from posthog.schema import PersonsQuery, PersonsQueryResponse, LifecycleQuery


class PersonsQueryRunner(QueryRunner):
    query: PersonsQuery

    def __init__(self, query: PersonsQuery | Dict[str, Any], team: Team, timings: Optional[HogQLTimings] = None):
        super().__init__(team, timings)
        if isinstance(query, PersonsQuery):
            self.query = query
        else:
            self.query = PersonsQuery.model_validate(query)

    def run(self) -> PersonsQueryResponse:
        response = execute_hogql_query(
            query_type="PersonsQuery",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
        )
        return PersonsQueryResponse(
            results=response.results,
            timings=response.timings,
            hogql=response.hogql,
            columns=[],
            types=[],
        )

    def to_query(self) -> ast.SelectQuery:
        where_exprs: List[ast.Expr] = []

        if self.query.properties:
            where_exprs.append(property_to_expr(self.query.properties, self.team, scope="person"))

        if self.query.fixedProperties:
            where_exprs.append(property_to_expr(self.query.fixedProperties, self.team, scope="person"))

        if self.query.source:
            source = self.query.source
            if isinstance(source, LifecycleQuery):
                source_query = get_query_runner(source, self.team, self.timings).to_persons_query()
                where_exprs.append(
                    ast.CompareOperation(op=ast.CompareOperationOp.In, left=ast.Field(chain=["id"]), right=source_query)
                )
            else:
                raise ValueError(f"Queries of type '{source.kind}' are not supported as a PersonsQuery sources.")

        if self.query.search is not None and self.query.search != "":
            where_exprs.append(
                ast.Or(
                    exprs=[
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.ILike,
                            left=ast.Field(chain=["properties", "email"]),
                            right=ast.Constant(value=f"%{self.query.search}%"),
                        ),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.ILike,
                            left=ast.Field(chain=["properties", "name"]),
                            right=ast.Constant(value=f"%{self.query.search}%"),
                        ),
                        # ast.CompareOperation(
                        #     op=ast.CompareOperationOp.Like,
                        #     left=ast.Field(chain=["distinct_id"]),
                        #     right=ast.Constant(value=f"%{self.query.search}%"),
                        # ),
                    ]
                )
            )

        if len(where_exprs) == 0:
            where = ast.Constant(value=True)
        elif len(where_exprs) == 1:
            where = where_exprs[0]
        else:
            where = ast.And(exprs=where_exprs)

        # adding +1 to the limit to check if there's a "next page" after the requested results
        from posthog.hogql.constants import DEFAULT_RETURNED_ROWS, MAX_SELECT_RETURNED_ROWS

        limit = (
            min(MAX_SELECT_RETURNED_ROWS, DEFAULT_RETURNED_ROWS if self.query.limit is None else self.query.limit) + 1
        )
        offset = 0 if self.query.offset is None else self.query.offset

        with self.timings.measure("select"):
            stmt = ast.SelectQuery(
                select=[],
                select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
                where=where,
                # having=having,
                # group_by=group_by if has_any_aggregation else None,
                # order_by=order_by,
                limit=ast.Constant(value=limit),
                offset=ast.Constant(value=offset),
            )

        return stmt

    def to_persons_query(self) -> ast.SelectQuery:
        return self.to_query()
