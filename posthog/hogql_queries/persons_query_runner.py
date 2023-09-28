import json
from datetime import timedelta
from typing import Optional, Any, Dict, List

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr
from posthog.hogql.property import property_to_expr, has_aggregation
from posthog.hogql.query import execute_hogql_query
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.models import Team
from posthog.schema import PersonsQuery, PersonsQueryResponse, LifecycleQuery

SELECT_STAR_FROM_PERSONS_FIELDS = ["id", "properties", "created_at", "is_identified"]


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
        input_columns = self.input_columns()
        if "*" in input_columns:
            star_idx = input_columns.index("*")
            for index, result in enumerate(response.results):
                response.results[index] = list(result)
                select = result[star_idx]
                new_result = dict(zip(SELECT_STAR_FROM_PERSONS_FIELDS, select))
                new_result["properties"] = json.loads(new_result["properties"])
                response.results[index][star_idx] = new_result
        return PersonsQueryResponse(
            results=response.results,
            timings=response.timings,
            hogql=response.hogql,
            columns=self.input_columns(),
            types=[type for _, type in response.types],
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
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.ILike,
                            left=ast.Call(name="toString", args=[ast.Field(chain=["id"])]),
                            right=ast.Constant(value=f"%{self.query.search}%"),
                        ),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.Like,
                            left=ast.Field(chain=["distinct_ids", "distinct_id"]),
                            right=ast.Constant(value=f"%{self.query.search}%"),
                        ),
                    ]
                )
            )
        return where_exprs

    def input_columns(self) -> List[str]:
        return self.query.select or ["*", "person", "id", "created_at", "person.$delete"]

    def to_query(self) -> ast.SelectQuery:
        # adding +1 to the limit to check if there's a "next page" after the requested results
        from posthog.hogql.constants import DEFAULT_RETURNED_ROWS, MAX_SELECT_RETURNED_ROWS

        with self.timings.measure("columns"):
            columns = []
            for expr in self.input_columns():
                if expr == "person.$delete":
                    columns.append(ast.Constant(value=1))
                elif expr == "person":
                    columns.append(ast.Constant(value=1))
                elif expr == "*":
                    columns.append(
                        ast.Tuple(exprs=[ast.Field(chain=[field]) for field in SELECT_STAR_FROM_PERSONS_FIELDS])
                    )
                else:
                    columns.append(parse_expr(expr))
            group_by: List[ast.Expr] = [column for column in columns if not has_aggregation(column)]
            aggregations: List[ast.Expr] = [column for column in columns if has_aggregation(column)]
            has_any_aggregation = len(aggregations) > 0

        with self.timings.measure("filters"):
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
                select=columns,
                select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
                where=where,
                having=having,
                group_by=group_by if has_any_aggregation else None,
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
