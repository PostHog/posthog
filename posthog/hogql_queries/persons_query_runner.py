from datetime import timedelta
from typing import List, cast, Literal, Dict, Generator, Sequence, Iterator
from django.db.models.query import Prefetch
from posthog.hogql import ast
from posthog.hogql.constants import get_max_limit_for_context, get_default_limit_for_context
from posthog.hogql.parser import parse_expr, parse_order_expr
from posthog.hogql.property import property_to_expr, has_aggregation
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.models import Person, Group
from posthog.schema import PersonsQuery, PersonsQueryResponse, InsightPersonsQuery, StickinessQuery, LifecycleQuery


class PersonsQueryRunner(QueryRunner):
    query: PersonsQuery
    query_type = PersonsQuery

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator(limit=self.query_limit(), offset=self.query.offset or 0)

    @property
    def aggregation_group_type_index(self) -> int | None:
        if (
            not self.query.source
            or not isinstance(self.query.source, InsightPersonsQuery)
            or isinstance(self.query.source.source, StickinessQuery)
            or isinstance(self.query.source.source, LifecycleQuery)
        ):
            return None
        try:
            return self.query.source.source.aggregation_group_type_index
        except AttributeError:
            return None

    def get_persons(self, person_ids) -> Dict[str, Dict]:
        return {
            str(p.uuid): {
                "id": p.uuid,
                **{field: getattr(p, field) for field in ("distinct_ids", "properties", "created_at", "is_identified")},
            }  # TODO: Use pydantic model?
            for p in Person.objects.filter(
                team_id=self.team.pk, persondistinctid__team_id=self.team.pk, uuid__in=person_ids
            )
            .prefetch_related(Prefetch("persondistinctid_set", to_attr="distinct_ids_cache"))
            .iterator(chunk_size=self.paginator.limit)
        }

    def get_groups(self, group_type_index, group_ids) -> Dict[str, Dict]:
        return {
            str(p["group_key"]): {
                "id": p["group_key"],
                "type": "group",
                "properties": p["group_properties"],  # TODO: Legacy for frontend
                **p,
            }
            for p in Group.objects.filter(
                team_id=self.team.pk, group_type_index=group_type_index, group_key__in=group_ids
            )
            .values("group_key", "group_type_index", "created_at", "group_properties")
            .iterator(chunk_size=self.paginator.limit)
        }

    def get_actors_from_result(self, actor_ids) -> Dict[str, Dict]:
        if self.aggregation_group_type_index is not None:
            return self.get_groups(self.aggregation_group_type_index, actor_ids)

        return self.get_persons(actor_ids)

    def enrich_with_actors(self, results, actor_column_index, actors_lookup) -> Generator[List, None, None]:
        for result in results:
            new_row = list(result)
            actor_id = str(result[actor_column_index])
            actor = actors_lookup.get(actor_id)
            new_row[actor_column_index] = actor if actor else {"id": actor_id}
            yield new_row

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
        results: Sequence[List] | Iterator[List] = self.paginator.results

        enrich_columns = filter(lambda column: column in ("person", "group", "actor"), input_columns)
        for column_name in enrich_columns:
            actor_ids = (row[input_columns.index(column_name)] for row in self.paginator.results)
            actors_lookup = self.get_actors_from_result(actor_ids)
            missing_actors_count = len(self.paginator.results) - len(actors_lookup)
            results = self.enrich_with_actors(results, input_columns.index(column_name), actors_lookup)

        return PersonsQueryResponse(
            results=results,
            timings=response.timings,
            types=[t for _, t in response.types] if response.types else None,
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
        if self.query.select:
            return self.query.select

        if self.aggregation_group_type_index is not None:
            return ["group"]

        return ["person", "id", "created_at", "person.$delete"]

    def query_limit(self) -> int:
        max_rows = get_max_limit_for_context(self.limit_context)
        default_rows = get_default_limit_for_context(self.limit_context)
        return min(max_rows, default_rows if self.query.limit is None else self.query.limit)

    def source_id_column(self, source_query: ast.SelectQuery) -> List[str]:
        # Figure out the id column of the source query, first column that has id in the name
        for column in source_query.select:
            if isinstance(column, ast.Field) and any("id" in part.lower() for part in column.chain):
                return column.chain
        raise ValueError("Source query must have an id column")

    def source_table_join(self) -> ast.JoinExpr:
        assert self.query.source is not None  # For type checking
        source_query_runner = get_query_runner(self.query.source, self.team, self.timings)
        source_query = source_query_runner.to_persons_query()
        source_id_chain = self.source_id_column(source_query)
        source_alias = "source"
        origin = "persons" if self.aggregation_group_type_index is None else "groups"
        origin_id = "id" if self.aggregation_group_type_index is None else "key"

        return ast.JoinExpr(
            table=ast.Field(chain=[origin]),
            next_join=ast.JoinExpr(
                table=source_query,
                join_type="INNER JOIN",
                alias=source_alias,
                constraint=ast.JoinConstraint(
                    expr=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=[origin, origin_id]),
                        right=ast.Field(chain=[source_alias, *source_id_chain]),
                    )
                ),
            ),
        )

    def to_query(self) -> ast.SelectQuery:
        with self.timings.measure("columns"):
            columns = []
            group_by = []
            aggregations = []
            for expr in self.input_columns():
                if expr == "person.$delete":
                    column = ast.Constant(value=1)
                elif expr == "person" or (expr == "actor" and self.aggregation_group_type_index is None):
                    column = ast.Field(chain=["id"])
                elif expr == "group" or (expr == "actor" and self.aggregation_group_type_index is not None):
                    column = ast.Field(chain=["key"])
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
                join_expr = self.source_table_join()
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
