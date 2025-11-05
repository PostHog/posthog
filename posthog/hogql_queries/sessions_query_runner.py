from datetime import timedelta
from typing import Optional

from django.utils.timezone import now

from posthog.schema import CachedSessionsQueryResponse, DashboardFilter, SessionsQuery, SessionsQueryResponse

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_order_expr
from posthog.hogql.property import has_aggregation, map_virtual_properties, property_to_expr

from posthog.api.utils import get_pk_or_uuid
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import AnalyticsQueryRunner
from posthog.models import Person
from posthog.models.person.person import READ_DB_FOR_PERSONS, get_distinct_ids_for_subquery
from posthog.utils import relative_date_parse

# Allow-listed fields returned when you select "*" from sessions
SELECT_STAR_FROM_SESSIONS_FIELDS = [
    "session_id",
    "distinct_id",
    "$start_timestamp",
    "$end_timestamp",
    "$session_duration",
    "$entry_current_url",
    "$end_current_url",
    "$pageview_count",
    "$autocapture_count",
    "$screen_count",
    "$is_bounce",
]


class SessionsQueryRunner(AnalyticsQueryRunner[SessionsQueryResponse]):
    query: SessionsQuery
    cached_response: CachedSessionsQueryResponse

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=self.limit_context, limit=self.query.limit, offset=self.query.offset
        )

    def select_cols(self) -> tuple[list[str], list[ast.Expr]]:
        select_input: list[str] = []
        for col in self.select_input_raw():
            # Selecting a "*" expands the list of columns
            if col == "*":
                select_input.append(f"tuple({', '.join(SELECT_STAR_FROM_SESSIONS_FIELDS)})")
            else:
                select_input.append(col)
        return select_input, [
            map_virtual_properties(parse_expr(column, timings=self.timings)) for column in select_input
        ]

    def to_query(self) -> ast.SelectQuery:
        with self.timings.measure("build_ast"):
            # columns & group_by
            with self.timings.measure("columns"):
                select_input, select = self.select_cols()

            with self.timings.measure("aggregations"):
                group_by: list[ast.Expr] = [column for column in select if not has_aggregation(column)]
                aggregations: list[ast.Expr] = [column for column in select if has_aggregation(column)]
                has_any_aggregation = len(aggregations) > 0

            # filters
            with self.timings.measure("filters"):
                with self.timings.measure("where"):
                    where_input = self.query.where or []
                    where_exprs = [parse_expr(expr, timings=self.timings) for expr in where_input]
                if self.query.properties:
                    with self.timings.measure("properties"):
                        where_exprs.extend(property_to_expr(property, self.team) for property in self.query.properties)
                if self.query.fixedProperties:
                    with self.timings.measure("fixed_properties"):
                        where_exprs.extend(
                            property_to_expr(property, self.team) for property in self.query.fixedProperties
                        )
                if self.query.personId:
                    with self.timings.measure("person_id"):
                        person: Optional[Person] = get_pk_or_uuid(
                            Person.objects.db_manager(READ_DB_FOR_PERSONS).filter(team=self.team), self.query.personId
                        ).first()
                        where_exprs.append(
                            ast.CompareOperation(
                                left=ast.Call(name="cityHash64", args=[ast.Field(chain=["distinct_id"])]),
                                right=ast.Tuple(
                                    exprs=[
                                        ast.Call(name="cityHash64", args=[ast.Constant(value=id)])
                                        for id in get_distinct_ids_for_subquery(person, self.team)
                                    ]
                                ),
                                op=ast.CompareOperationOp.In,
                            )
                        )
                if self.query.filterTestAccounts:
                    with self.timings.measure("test_account_filters"):
                        for prop in self.team.test_account_filters or []:
                            where_exprs.append(property_to_expr(prop, self.team))

            with self.timings.measure("timestamps"):
                # prevent accidentally future sessions from being visible by default
                before = self.query.before or (now() + timedelta(seconds=5)).isoformat()
                parsed_date = relative_date_parse(before, self.team.timezone_info)
                where_exprs.append(
                    parse_expr(
                        "$start_timestamp < {timestamp}",
                        {"timestamp": ast.Constant(value=parsed_date)},
                        timings=self.timings,
                    )
                )

                # limit to the last 24h by default
                after = self.query.after or "-24h"
                if after != "all":
                    parsed_date = relative_date_parse(after, self.team.timezone_info)
                    where_exprs.append(
                        parse_expr(
                            "$start_timestamp > {timestamp}",
                            {"timestamp": ast.Constant(value=parsed_date)},
                            timings=self.timings,
                        )
                    )

            # where & having
            with self.timings.measure("where"):
                where_list = [expr for expr in where_exprs if not has_aggregation(expr)]
                where: ast.Expr | None = ast.And(exprs=where_list) if len(where_list) > 0 else None
                having_list = [expr for expr in where_exprs if has_aggregation(expr)]
                having: ast.Expr | None = ast.And(exprs=having_list) if len(having_list) > 0 else None

            # order by
            with self.timings.measure("order"):
                if self.query.orderBy is not None:
                    order_by = [parse_order_expr(column, timings=self.timings) for column in self.query.orderBy]
                elif "count()" in select_input:
                    order_by = [ast.OrderExpr(expr=parse_expr("count()"), order="DESC")]
                elif len(aggregations) > 0:
                    order_by = [ast.OrderExpr(expr=aggregations[0], order="DESC")]
                elif "$start_timestamp" in select_input:
                    order_by = [ast.OrderExpr(expr=ast.Field(chain=["$start_timestamp"]), order="DESC")]
                elif len(select) > 0:
                    order_by = [ast.OrderExpr(expr=select[0], order="ASC")]
                else:
                    order_by = []

            with self.timings.measure("select"):
                stmt = ast.SelectQuery(
                    select=select,
                    select_from=ast.JoinExpr(table=ast.Field(chain=["sessions"])),
                    where=where,
                    having=having,
                    group_by=group_by if has_any_aggregation else None,
                    order_by=order_by,
                )

                return stmt

    def _calculate(self) -> SessionsQueryResponse:
        query_result = self.paginator.execute_hogql_query(
            query=self.to_query(),
            team=self.team,
            query_type="SessionsQuery",
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )

        # Convert star field from tuple to dict in each result
        if "*" in self.select_input_raw():
            with self.timings.measure("expand_asterisk"):
                star_idx = self.select_input_raw().index("*")
                for index, result in enumerate(self.paginator.results):
                    self.paginator.results[index] = list(result)
                    select = result[star_idx]
                    new_result = dict(zip(SELECT_STAR_FROM_SESSIONS_FIELDS, select))
                    self.paginator.results[index][star_idx] = new_result

        return SessionsQueryResponse(
            results=self.paginator.results,
            columns=self.columns(query_result.columns),
            types=[t for _, t in query_result.types] if query_result.types else [],
            timings=self.timings.to_list(),
            hogql=query_result.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )

    def apply_dashboard_filters(self, dashboard_filter: DashboardFilter):
        if dashboard_filter.date_to or dashboard_filter.date_from:
            self.query.before = dashboard_filter.date_to
            self.query.after = dashboard_filter.date_from

        if dashboard_filter.properties:
            self.query.properties = (self.query.properties or []) + dashboard_filter.properties

    def columns(self, result_columns: list | None) -> list[str]:
        _, select = self.select_cols()
        columns = result_columns or []
        return [
            columns[idx] if len(columns) > idx and isinstance(select[idx], ast.Alias) else col
            for idx, col in enumerate(self.select_input_raw())
        ]

    def select_input_raw(self) -> list[str]:
        return ["*"] if len(self.query.select) == 0 else self.query.select
