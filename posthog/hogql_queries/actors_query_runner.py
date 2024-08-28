import itertools
from typing import Optional
from collections.abc import Sequence, Iterator

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_expr, parse_order_expr
from posthog.hogql.property import has_aggregation
from posthog.hogql_queries.actor_strategies import ActorStrategy, PersonStrategy, GroupStrategy
from posthog.hogql_queries.insights.funnels.funnels_query_runner import FunnelsQueryRunner
from posthog.hogql_queries.insights.insight_actors_query_runner import InsightActorsQueryRunner
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunner, get_query_runner
from posthog.schema import (
    ActorsQuery,
    ActorsQueryResponse,
    CachedActorsQueryResponse,
    DashboardFilter,
)


class ActorsQueryRunner(QueryRunner):
    query: ActorsQuery
    response: ActorsQueryResponse
    cached_response: CachedActorsQueryResponse

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

    @staticmethod
    def _get_recordings(event_results: list, recordings_lookup: dict) -> list[dict]:
        return [
            {"session_id": session_id, "events": recordings_lookup[session_id]}
            for session_id in {event[2] for event in event_results}
            if session_id in recordings_lookup
        ]

    def _enrich_with_actors(
        self,
        results,
        actor_column_index,
        actors_lookup,
        recordings_column_index: Optional[int],
        recordings_lookup: Optional[dict[str, list[dict]]],
    ) -> list:
        enriched = []

        for result in results:
            new_row = list(result)
            actor_id = str(result[actor_column_index])
            actor = actors_lookup.get(actor_id)
            new_row[actor_column_index] = actor if actor else {"id": actor_id}
            if recordings_column_index is not None and recordings_lookup is not None:
                new_row[recordings_column_index] = (
                    self._get_recordings(result[recordings_column_index], recordings_lookup) or []
                )

            enriched.append(new_row)

        return enriched

    def prepare_recordings(
        self, column_name: str, input_columns: list[str]
    ) -> tuple[int | None, dict[str, list[dict]] | None]:
        if (column_name != "person" and column_name != "actor") or "matched_recordings" not in input_columns:
            return None, None

        column_index_events = input_columns.index("matched_recordings")
        matching_events_list = itertools.chain.from_iterable(row[column_index_events] for row in self.paginator.results)
        return column_index_events, self.strategy.get_recordings(matching_events_list)

    def calculate(self) -> ActorsQueryResponse:
        # Funnel queries require the experimental analyzer to run correctly
        # Can remove once clickhouse moves to version 24.3 or above
        settings = None
        if isinstance(self.source_query_runner, InsightActorsQueryRunner) and isinstance(
            self.source_query_runner.source_runner, FunnelsQueryRunner
        ):
            settings = HogQLGlobalSettings(allow_experimental_analyzer=True)

        response = self.paginator.execute_hogql_query(
            query_type="ActorsQuery",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
            settings=settings,
        )
        input_columns = self.input_columns()
        missing_actors_count = None
        results: Sequence[list] | Iterator[list] = self.paginator.results

        enrich_columns = filter(lambda column: column in ("person", "group", "actor"), input_columns)
        for column_name in enrich_columns:
            actor_column_index = input_columns.index(column_name)
            actor_ids = (row[actor_column_index] for row in self.paginator.results)
            actors_lookup = self.strategy.get_actors(actor_ids)

            recordings_column_index, recordings_lookup = self.prepare_recordings(column_name, input_columns)

            missing_actors_count = len(self.paginator.results) - len(actors_lookup)
            results = self._enrich_with_actors(
                results, actor_column_index, actors_lookup, recordings_column_index, recordings_lookup
            )

        return ActorsQueryResponse(
            results=results,
            timings=response.timings,
            types=[t for _, t in response.types] if response.types else None,
            columns=input_columns,
            hogql=response.hogql,
            modifiers=self.modifiers,
            missing_actors_count=missing_actors_count,
            **self.paginator.response_params(),
        )

    def input_columns(self) -> list[str]:
        if self.query.select:
            return self.query.select

        return self.strategy.input_columns()

    # TODO: Figure out a more sure way of getting the actor id than using the alias or chain name
    def source_id_column(self, source_query: ast.SelectQuery | ast.SelectUnionQuery) -> list[str]:
        # Figure out the id column of the source query, first column that has id in the name
        if isinstance(source_query, ast.SelectQuery):
            select = source_query.select
        else:
            select = source_query.select_queries[0].select

        for column in select:
            if isinstance(column, ast.Alias) and (column.alias in ("group_key", "actor_id", "person_id")):
                return [column.alias]

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
            table=source_query,
            alias=source_alias,
            next_join=ast.JoinExpr(
                table=ast.Field(chain=[self.strategy.origin]),
                join_type="INNER JOIN",
                constraint=ast.JoinConstraint(
                    expr=ast.CompareOperation(
                        op=ast.CompareOperationOp.Eq,
                        left=ast.Field(chain=[self.strategy.origin, self.strategy.origin_id]),
                        right=ast.Field(chain=[source_alias, *source_id_chain]),
                    ),
                    constraint_type="ON",
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
                elif expr == self.strategy.field or expr == "actor":
                    column = ast.Field(chain=[self.strategy.origin_id])
                elif expr == "matched_recordings":
                    # the underlying query used to match recordings compares to a selection of "matched events"
                    # like `groupUniqArray(100)(tuple(timestamp, uuid, `$session_id`, `$window_id`)) AS matching_events`
                    # we look up valid session ids and match them against the session ids in matching events
                    column = ast.Field(chain=["matching_events"])

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

        order_by: list[ast.OrderExpr]
        with self.timings.measure("order"):
            if self.query.orderBy is not None:
                strategy_order_by = self.strategy.order_by()
                if strategy_order_by is not None:
                    order_by = strategy_order_by
                else:
                    order_by = [parse_order_expr(col, timings=self.timings) for col in self.query.orderBy]
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
            if not self.query.source:
                join_expr = ast.JoinExpr(table=ast.Field(chain=[self.strategy.origin]))
            else:
                assert self.source_query_runner is not None  # For type checking
                source_query = self.source_query_runner.to_actors_query()

                source_id_chain = self.source_id_column(source_query)
                source_alias = "source"

                origin = self.strategy.origin

                join_on: ast.Expr = ast.CompareOperation(
                    op=ast.CompareOperationOp.Eq,
                    left=ast.Field(chain=[origin, self.strategy.origin_id]),
                    right=ast.Field(chain=[source_alias, *source_id_chain]),
                )

                # For some of our users, the persons table is large. If we're looking for person,
                # help make the join smarter by limiting the people it has to look up
                # The persons table inlines `in` conditions on the join (see `persons.py`)
                # Funnels queries are very big. Don't do this for funnels as it blows up the query size.
                if isinstance(self.strategy, PersonStrategy) and not (
                    isinstance(self.source_query_runner, InsightActorsQueryRunner)
                    and isinstance(self.source_query_runner.source_runner, FunnelsQueryRunner)
                ):
                    join_on = ast.And(
                        exprs=[
                            join_on,
                            ast.CompareOperation(
                                left=ast.Field(chain=[origin, "id"]),
                                right=ast.SelectQuery(
                                    select=[ast.Field(chain=[source_alias, *self.source_id_column(source_query)])],
                                    select_from=ast.JoinExpr(table=source_query, alias=source_alias),
                                ),
                                op=ast.CompareOperationOp.In,
                            ),
                        ]
                    )

                join_expr = ast.JoinExpr(
                    table=source_query,
                    alias=source_alias,
                    next_join=ast.JoinExpr(
                        table=ast.Field(chain=[origin]),
                        join_type="INNER JOIN",
                        constraint=ast.JoinConstraint(
                            expr=join_on,
                            constraint_type="ON",
                        ),
                    ),
                )

        return ast.SelectQuery(
            select=columns,
            select_from=join_expr,
            where=where,
            having=having,
            group_by=group_by if has_any_aggregation else None,
            order_by=order_by,
        )

    def to_actors_query(self) -> ast.SelectQuery:
        return self.to_query()

    def apply_dashboard_filters(self, dashboard_filter: DashboardFilter):
        if self.source_query_runner:
            self.source_query_runner.apply_dashboard_filters(dashboard_filter)

    def _remove_aliases(self, node: ast.Expr) -> ast.Expr:
        if isinstance(node, ast.Alias):
            return self._remove_aliases(node.expr)
        return node
