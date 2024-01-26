import itertools
from datetime import timedelta
from typing import List, Generator, Sequence, Iterator, Optional
from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_order_expr
from posthog.hogql.property import has_aggregation
from posthog.hogql_queries.actor_strategies import ActorStrategy, PersonStrategy, GroupStrategy
from posthog.hogql_queries.insights.insight_actors_query_runner import InsightActorsQueryRunner
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.schema import ActorsQuery, ActorsQueryResponse


class ActorsQueryRunner(QueryRunner):
    query: ActorsQuery
    query_type = ActorsQuery

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=self.limit_context, limit=self.query.limit, offset=self.query.offset
        )
        self.source_query_runner: Optional[QueryRunner] = None

        if self.query.source:
            self.source_query_runner = get_query_runner(self.query.source, self.team, self.timings, self.limit_context)

        self.strategy = self.determine_strategy()

    @property
    def group_type_index(self) -> int | None:
        if not self.source_query_runner or not isinstance(self.source_query_runner, InsightActorsQueryRunner):
            return None

        return self.source_query_runner.group_type_index

    def determine_strategy(self) -> ActorStrategy:
        if self.group_type_index is not None:
            return GroupStrategy(self.group_type_index, team=self.team, query=self.query, paginator=self.paginator)
        return PersonStrategy(team=self.team, query=self.query, paginator=self.paginator)

    def get_recordings(self, event_results, recordings_lookup) -> Generator[dict, None, None]:
        return (
            {"session_id": session_id, "events": recordings_lookup[session_id]}
            for session_id in (event[2] for event in event_results)
            if session_id in recordings_lookup
        )

    def enrich_with_actors(
        self,
        results,
        actor_column_index,
        actors_lookup,
        column_index_events: Optional[int],
        recordings_lookup: Optional[dict[str, list[dict]]],
    ) -> Generator[List, None, None]:
        for result in results:
            new_row = list(result)
            actor_id = str(result[actor_column_index])
            actor = actors_lookup.get(actor_id)
            new_row[actor_column_index] = actor if actor else {"id": actor_id}
            if column_index_events and recordings_lookup:
                new_row[column_index_events] = self.get_recordings(result[column_index_events], recordings_lookup)
            yield new_row

    def prepare_recordings(self, column_name, input_columns):
        if column_name != "person" or "matched_recordings" not in input_columns:
            return None, None

        column_index_events = input_columns.index("matched_recordings")
        matching_events_list = itertools.chain.from_iterable(
            (row[column_index_events] for row in self.paginator.results)
        )
        return column_index_events, self.strategy.get_recordings(matching_events_list)

    def calculate(self) -> ActorsQueryResponse:
        response = self.paginator.execute_hogql_query(
            query_type="ActorsQuery",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )
        input_columns = self.input_columns()
        missing_actors_count = None
        results: Sequence[List] | Iterator[List] = self.paginator.results

        enrich_columns = filter(lambda column: column in ("person", "group"), input_columns)
        for column_name in enrich_columns:
            column_index_actor = input_columns.index(column_name)
            actor_ids = (row[column_index_actor] for row in self.paginator.results)
            actors_lookup = self.strategy.get_actors(actor_ids)
            column_index_events, recordings_lookup = self.prepare_recordings(column_name, input_columns)

            missing_actors_count = len(self.paginator.results) - len(actors_lookup)
            results = self.enrich_with_actors(
                results, column_index_actor, actors_lookup, column_index_events, recordings_lookup
            )

        return ActorsQueryResponse(
            results=results,
            timings=response.timings,
            types=[t for _, t in response.types] if response.types else None,
            columns=input_columns,
            hogql=response.hogql,
            missing_actors_count=missing_actors_count,
            **self.paginator.response_params(),
        )

    def input_columns(self) -> List[str]:
        if self.query.select:
            return self.query.select

        return self.strategy.input_columns()

    # TODO: Figure out a more sure way of getting the actor id than using the alias or chain name
    def source_id_column(self, source_query: ast.SelectQuery | ast.SelectUnionQuery) -> List[str]:
        # Figure out the id column of the source query, first column that has id in the name
        if isinstance(source_query, ast.SelectQuery):
            select = source_query.select
        else:
            select = source_query.select_queries[0].select

        for column in select:
            if isinstance(column, ast.Alias) and "id" in column.alias:
                return [column.alias]

            if isinstance(column, ast.Field) and any("id" in str(part).lower() for part in column.chain):
                return [str(part) for part in column.chain]
        raise ValueError("Source query must have an id column")

    def source_table_join(self) -> ast.JoinExpr:
        assert self.source_query_runner is not None  # For type checking
        source_query = self.source_query_runner.to_actors_query()
        source_id_chain = self.source_id_column(source_query)
        source_alias = "source"

        return ast.JoinExpr(
            table=ast.Field(chain=[self.strategy.origin]),
            next_join=ast.JoinExpr(
                table=source_query,
                join_type="INNER JOIN",
                alias=source_alias,
                constraint=ast.JoinConstraint(
                    expr=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=[self.strategy.origin, self.strategy.origin_id]),
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
                column: ast.Expr = parse_expr(expr)

                if expr == "person.$delete":
                    column = ast.Constant(value=1)
                elif expr == self.strategy.field:
                    column = ast.Field(chain=[self.strategy.origin_id])
                elif expr == "matched_recordings":
                    column = ast.Field(chain=["matching_events"])  # TODO: Hmm?

                columns.append(column)
                if has_aggregation(column):
                    aggregations.append(column)
                elif not isinstance(column, ast.Constant):
                    group_by.append(column)
            has_any_aggregation = len(aggregations) > 0

        with self.timings.measure("filters"):
            filter_conditions = self.strategy.filter_conditions()
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
                strategy_order_by = self.strategy.order_by()
                if strategy_order_by is not None:
                    order_by = strategy_order_by
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
                join_expr = ast.JoinExpr(table=ast.Field(chain=[self.strategy.origin]))

            stmt = ast.SelectQuery(
                select=columns,
                select_from=join_expr,
                where=where,
                having=having,
                group_by=group_by if has_any_aggregation else None,
                order_by=order_by,
            )

        return stmt

    def to_actors_query(self) -> ast.SelectQuery:
        return self.to_query()

    def _is_stale(self, cached_result_package):
        return True

    def _refresh_frequency(self):
        return timedelta(minutes=1)

    def _remove_aliases(self, node: ast.Expr) -> ast.Expr:
        if isinstance(node, ast.Alias):
            return self._remove_aliases(node.expr)
        return node
