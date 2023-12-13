from datetime import timedelta
from typing import List, cast, Literal, Union

from posthog.hogql import ast
from posthog.hogql.constants import get_max_limit_for_context, get_default_limit_for_context
from posthog.hogql.parser import parse_expr, parse_order_expr
from posthog.hogql.property import property_to_expr, has_aggregation
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.queries.actor_base_query import SerializedGroup, SerializedPerson, get_groups, get_people
from posthog.schema import PersonsQuery, PersonsQueryResponse


class PersonsQueryRunner(QueryRunner):
    query: PersonsQuery
    query_type = PersonsQuery

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator(limit=self.query_limit(), offset=self.query.offset or 0)

    def get_actors_from_result(self, result):
        serialized_actors: Union[List[SerializedGroup], List[SerializedPerson]]

        actor_ids = [row[0] for row in result]
        value_per_actor_id = None

        # TODO: Make sure group stuff is correct
        if self.query.source.source.aggregation_group_type_index is not None:
            _, serialized_actors = get_groups(
                self.team.pk,
                self.query.source.source.aggregation_group_type_index,
                actor_ids,
                value_per_actor_id,
            )
        else:
            _, serialized_actors = get_people(self.team, actor_ids, value_per_actor_id)

        return serialized_actors

    def enrich_with_actors(self, actor_column_index):
        serialized_actors = self.get_actors_from_result(self.paginator.results)
        actors_lookup = {str(actor["id"]): actor for actor in serialized_actors}

        enriched_results = []
        for result in self.paginator.results:
            new_row = list(result)
            actor_id = str(result[actor_column_index])
            actor = actors_lookup.get(actor_id)
            new_row[actor_column_index] = actor if actor else {"id": actor_id}
            enriched_results.append(new_row)
        missing_actors_count = len(self.paginator.results) - len(actors_lookup)
        return enriched_results, missing_actors_count

    def calculate(self) -> PersonsQueryResponse:
        response = self.paginator.execute_hogql_query(
            query_type="PersonsQuery",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )
        input_columns = self.input_columns()
        missing_actors_count = None
        results = self.paginator.results

        if "person" in input_columns:
            results, missing_actors_count = self.enrich_with_actors(input_columns.index("person"))

        return PersonsQueryResponse(
            results=results,
            timings=response.timings,
            types=[type for _, type in response.types],
            columns=input_columns,
            hogql=response.hogql,
            missing_actors_count=missing_actors_count,
            **self.paginator.response_params(),
        )

    def filter_conditions(self) -> List[ast.Expr]:
        where_exprs: List[ast.Expr] = []

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
        # TODO: Make sure this group stuff is correct
        if self.query.source.source.aggregation_group_type_index is not None:
            # Take shortcut and deliver the source query as is
            source_query_runner = get_query_runner(self.query.source, self.team, self.timings)
            return source_query_runner.to_persons_query()

        with self.timings.measure("columns"):
            columns = []
            group_by = []
            aggregations = []
            for expr in self.input_columns():
                if expr == "person.$delete":
                    column = ast.Constant(value=1)
                elif expr == "person":
                    column = ast.Field(chain=["id"])
                else:
                    column = parse_expr(expr)
                columns.append(column)
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

        with self.timings.measure("select"):
            if self.query.source:
                source_query_runner = get_query_runner(self.query.source, self.team, self.timings)
                source_query = source_query_runner.to_persons_query()
                # Figure out the id column of the source query, first column that has id in the name
                source_id_column = None
                for column in source_query.select:
                    if isinstance(column, ast.Field) and any("id" in part.lower() for part in column.chain):
                        source_id_column = column.chain[-1]
                        break
                source_alias = "source"
                join_expr = ast.JoinExpr(
                    table=ast.Field(chain=["persons"]),
                    next_join=ast.JoinExpr(
                        table=source_query,
                        join_type="INNER JOIN",
                        alias=source_alias,
                        constraint=ast.JoinConstraint(
                            expr=ast.CompareOperation(
                                op=ast.CompareOperationOp.Eq,
                                left=ast.Field(chain=["persons", "id"]),
                                right=ast.Field(chain=[source_alias, source_id_column]),
                            )
                        ),
                    ),
                )
            else:
                join_expr = ast.JoinExpr(table=ast.Field(chain=["persons"]))

            stmt = ast.SelectQuery(
                select=columns,
                select_from=join_expr,
                where=where,
                having=having,
                group_by=group_by if has_any_aggregation else None,
                order_by=order_by,
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
