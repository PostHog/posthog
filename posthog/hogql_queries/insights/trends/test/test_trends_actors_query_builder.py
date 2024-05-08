from typing import cast
from hogql_parser import parse_select
from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.printer import print_ast
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.trends.trends_actors_query_builder import TrendsActorsQueryBuilder
from posthog.schema import DateRange, EventsNode, IntervalType, TrendsQuery
from posthog.test.base import BaseTest

default_query = TrendsQuery(series=[EventsNode(event="$pageview")], dateRange=DateRange(date_from="-7d"))


class TestQueryBuilder(BaseTest):
    def setUp(self):
        super().setUp()

    def _get_builder(
        self, time_frame: str, series_index: int = 0, trends_query: TrendsQuery = default_query
    ) -> TrendsActorsQueryBuilder:
        timings = HogQLTimings()
        modifiers = create_default_modifiers_for_team(self.team)

        return TrendsActorsQueryBuilder(
            trends_query=trends_query,
            team=self.team,
            timings=timings,
            modifiers=modifiers,
            series_index=series_index,
            time_frame=time_frame,
        )

    def _print_hogql_expr(self, conditions: list[ast.Expr]):
        query = cast(ast.SelectQuery, parse_select("SELECT * FROM events"))
        query.where = ast.And(exprs=conditions)
        sql = print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "hogql",
        )
        return sql[sql.find("WHERE and(") + 10 : sql.find(") LIMIT 10000")]

    def test_date_range(self):
        builder = self._get_builder(time_frame="2023-05-08")

        date_expr = builder._date_where_expr()

        self.assertEqual(
            self._print_hogql_expr(date_expr),
            "greaterOrEquals(timestamp, toDateTime('2023-05-08 00:00:00.000000')), less(timestamp, toDateTime('2024-05-08 00:00:00.000000'))",
        )

    def test_date_range_with_timezone(self):
        self.team.timezone = "Europe/Berlin"
        builder = self._get_builder(time_frame="2023-05-08")

        date_expr = builder._date_where_expr()

        self.assertEqual(
            self._print_hogql_expr(date_expr),
            "greaterOrEquals(timestamp, toDateTime('2023-05-07 22:00:00.000000')), less(timestamp, toDateTime('2023-05-08 22:00:00.000000'))",
        )

    def test_date_range_hourly(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(update={"interval": IntervalType.hour}, deep=True)
        builder = self._get_builder(trends_query=trends_query, time_frame="2023-05-08T15:00:00")

        date_expr = builder._date_where_expr()

        self.assertEqual(
            self._print_hogql_expr(date_expr),
            "greaterOrEquals(timestamp, toDateTime('2023-05-08 13:00:00.000000')), less(timestamp, toDateTime('2023-05-08 14:00:00.000000'))",
        )
