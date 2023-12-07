import json
from datetime import timedelta
from typing import List, cast, Literal

from posthog.hogql import ast
from posthog.hogql.constants import get_max_limit_for_context, get_default_limit_for_context
from posthog.hogql.parser import parse_expr, parse_order_expr
from posthog.hogql.property import property_to_expr, has_aggregation
from posthog.hogql.query import execute_hogql_query
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.schema import PersonsQuery, PersonsQueryResponse

PERSON_FULL_TUPLE = ["id", "properties", "created_at", "is_identified"]


class PersonsQueryRunner(QueryRunner):
    query: PersonsQuery
    query_type = PersonsQuery

    def calculate(self) -> PersonsQueryResponse:
        response = execute_hogql_query(
            query_type="PersonsQuery",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )
        input_columns = self.input_columns()
        if "person" in input_columns:
            person_column_index = input_columns.index("person")
            for index, result in enumerate(response.results):
                response.results[index] = list(result)
                select = result[person_column_index]
                new_result = dict(zip(PERSON_FULL_TUPLE, select))
                new_result["properties"] = json.loads(new_result["properties"])
                response.results[index][person_column_index] = new_result

        has_more = len(response.results) > self.query_limit()
        return PersonsQueryResponse(
            # we added +1 before for pagination, remove the last element if there's more
            results=response.results[:-1] if has_more else response.results,
            timings=response.timings,
            types=[type for _, type in response.types],
            columns=self.input_columns(),
            hogql=response.hogql,
            hasMore=has_more,
        )

    def filter_conditions(self) -> List[ast.Expr]:
        where_exprs: List[ast.Expr] = []

        if self.query.source:
            source = self.query.source
            try:
                source_query_runner = get_query_runner(source, self.team, self.timings)
                source_query = source_query_runner.to_persons_query()
                where_exprs.append(
                    ast.CompareOperation(
                        left=ast.Field(chain=["id"]),
                        op=ast.CompareOperationOp.In,
                        right=source_query,
                    )
                )
            except NotImplementedError:
                raise ValueError(f"Queries of type '{source.kind}' are not implemented as a PersonsQuery sources.")

        if self.query.properties:
            where_exprs.append(property_to_expr(self.query.properties, self.team, scope="person"))

        if self.query.fixedProperties:
            where_exprs.append(property_to_expr(self.query.fixedProperties, self.team, scope="person"))

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
                            op=ast.CompareOperationOp.ILike,
                            left=ast.Field(chain=["pdi", "distinct_id"]),
                            right=ast.Constant(value=f"%{self.query.search}%"),
                        ),
                    ]
                )
            )
        return where_exprs

    def input_columns(self) -> List[str]:
        return self.query.select or ["person", "id", "created_at", "person.$delete"]

    def query_limit(self) -> int:
        max_rows = get_max_limit_for_context(self.limit_context)
        default_rows = get_default_limit_for_context(self.limit_context)
        return min(max_rows, default_rows if self.query.limit is None else self.query.limit)

    def to_query(self) -> ast.SelectQuery:
        with self.timings.measure("columns"):
            columns = []
            group_by = []
            aggregations = []
            for expr in self.input_columns():
                if expr == "person.$delete":
                    columns.append(ast.Constant(value=1))
                elif expr == "person":
                    tuple_exprs = []
                    for field in PERSON_FULL_TUPLE:
                        column = ast.Field(chain=[field])
                        tuple_exprs.append(column)
                        if has_aggregation(column):
                            aggregations.append(column)
                        elif not isinstance(column, ast.Constant):
                            group_by.append(column)
                    columns.append(ast.Tuple(exprs=tuple_exprs))
                else:
                    column = parse_expr(expr)
                    columns.append(parse_expr(expr))
                    if has_aggregation(column):
                        aggregations.append(column)
                    elif not isinstance(column, ast.Constant):
                        group_by.append(column)
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

        with self.timings.measure("order"):
            if self.query.orderBy is not None:
                if self.query.orderBy in [["person"], ["person DESC"], ["person ASC"]]:
                    order_property = (
                        "email"
                        if self.team.person_display_name_properties is None
                        else self.team.person_display_name_properties[0]
                    )
                    order_by = [
                        ast.OrderExpr(
                            expr=ast.Field(chain=["properties", order_property]),
                            order=cast(
                                Literal["ASC", "DESC"],
                                "DESC" if self.query.orderBy[0] == "person DESC" else "ASC",
                            ),
                        )
                    ]
                else:
                    order_by = [parse_order_expr(column, timings=self.timings) for column in self.query.orderBy]
            elif "count()" in self.input_columns():
                order_by = [ast.OrderExpr(expr=parse_expr("count()"), order="DESC")]
            elif len(aggregations) > 0:
                order_by = [ast.OrderExpr(expr=self._remove_aliases(aggregations[0]), order="DESC")]
            elif "created_at" in self.input_columns():
                order_by = [ast.OrderExpr(expr=ast.Field(chain=["created_at"]), order="DESC")]
            elif len(columns) > 0:
                order_by = [ast.OrderExpr(expr=self._remove_aliases(columns[0]), order="ASC")]
            else:
                order_by = []

        with self.timings.measure("limit"):
            # adding +1 to the limit to check if there's a "next page" after the requested results
            limit = self.query_limit() + 1
            offset = 0 if self.query.offset is None else self.query.offset

        with self.timings.measure("select"):
            stmt = ast.SelectQuery(
                select=columns,
                select_from=ast.JoinExpr(table=ast.Field(chain=["persons"])),
                where=where,
                having=having,
                group_by=group_by if has_any_aggregation else None,
                order_by=order_by,
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

    def _remove_aliases(self, node: ast.Expr) -> ast.Expr:
        if isinstance(node, ast.Alias):
            return self._remove_aliases(node.expr)
        return node
