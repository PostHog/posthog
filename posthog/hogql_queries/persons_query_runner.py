from datetime import timedelta
from typing import Optional, Any, Dict, List

from posthog.hogql import ast
from posthog.hogql.property import property_to_expr, has_aggregation
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.models import Team
from posthog.schema import PersonsQuery, PersonsQueryResponse, LifecycleQuery


class PersonsQueryRunner(QueryRunner):
    query: PersonsQuery
    query_type = PersonsQuery

    def __init__(self, query: PersonsQuery | Dict[str, Any], team: Team, timings: Optional[HogQLTimings] = None):
        super().__init__(query, team, timings)
        if isinstance(query, PersonsQuery):
            self.query = query
        else:
            self.query = PersonsQuery.model_validate(query)

    def calculate(self) -> PersonsQueryResponse:
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

    def filter_conditions(self) -> List[ast.Expr]:
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
        return where_exprs

    def columns(self) -> List[ast.Expr]:
        return []

    def to_query(self) -> ast.SelectQuery:
        # adding +1 to the limit to check if there's a "next page" after the requested results
        from posthog.hogql.constants import DEFAULT_RETURNED_ROWS, MAX_SELECT_RETURNED_ROWS

        with self.timings.measure("filter_conditions"):
            filter_conditions = self.filter_conditions()
            where_list = [expr for expr in filter_conditions if not has_aggregation(expr)]
            if len(where_list) == 0:
                where = None
            elif len(where_list) == 1:
                where = where_list[0]
            else:
                where = ast.And(exprs=where_list)

            having_list = [expr for expr in filter_conditions if has_aggregation(expr)]
            if len(having_list) == 0:
                having = None
            elif len(having_list) == 1:
                having = having_list[0]
            else:
                having = ast.And(exprs=having_list)

        with self.timings.measure("limit"):
            limit = (
                min(MAX_SELECT_RETURNED_ROWS, DEFAULT_RETURNED_ROWS if self.query.limit is None else self.query.limit)
                + 1
            )
            offset = 0 if self.query.offset is None else self.query.offset

        with self.timings.measure("select"):
            stmt = ast.SelectQuery(
                select=self.columns(),
                select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
                where=where,
                having=having,
                # group_by=group_by if has_any_aggregation else None,
                # order_by=order_by,
                limit=ast.Constant(value=limit),
                offset=ast.Constant(value=offset),
            )

        return stmt

    def to_persons_query(self) -> ast.SelectQuery:
        return self.to_query()

    def _is_stale(self, cached_result_package):
        return True

    def _refresh_frequency(self):
        return timedelta(minutes=1)
