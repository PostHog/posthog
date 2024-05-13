from datetime import datetime, timezone
from typing import Optional, cast

from freezegun import freeze_time
from hogql_parser import parse_select
from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.printer import print_ast
from posthog.hogql.timings import HogQLTimings
from posthog.hogql_queries.insights.trends.trends_actors_query_builder import TrendsActorsQueryBuilder
from posthog.schema import (
    BaseMathType,
    ChartDisplayType,
    Compare,
    DateRange,
    EventsNode,
    IntervalType,
    TrendsFilter,
    TrendsQuery,
)
from posthog.test.base import BaseTest

default_query = TrendsQuery(series=[EventsNode(event="$pageview")], dateRange=DateRange(date_from="-7d"))


class TestTrendsActorsQueryBuilder(BaseTest):
    maxDiff = None

    def setUp(self):
        super().setUp()

    def _get_builder(
        self,
        time_frame: Optional[str] = None,
        series_index: int = 0,
        trends_query: TrendsQuery = default_query,
        compare_value: Optional[Compare] = None,
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
            compare_value=compare_value,
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

    def _get_date_where_sql(self, **kwargs):
        builder = self._get_builder(**kwargs)
        date_expr = builder._date_where_expr()
        return self._print_hogql_expr(date_expr)

    def _get_utc_string(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")

    def test_time_frame(self):
        self.team.timezone = "Europe/Berlin"

        builder = self._get_builder(time_frame="2023-05-08")
        self.assertEqual(self._get_utc_string(builder.time_frame), "2023-05-07 22:00:00Z")

        builder = self._get_builder(time_frame="2023-05-08 15:00:00")
        self.assertEqual(self._get_utc_string(builder.time_frame), "2023-05-08 13:00:00Z")

        builder = self._get_builder(time_frame="2023-05-08T15:00:00Z")
        self.assertEqual(self._get_utc_string(builder.time_frame), "2023-05-08 15:00:00Z")

        builder = self._get_builder(time_frame="2023-05-08T15:00:00-07:00")
        self.assertEqual(self._get_utc_string(builder.time_frame), "2023-05-08 22:00:00Z")

    def test_date_range(self):
        self.assertEqual(
            self._get_date_where_sql(time_frame="2023-05-08"),
            "greaterOrEquals(timestamp, toDateTime('2023-05-08 00:00:00.000000')), less(timestamp, toDateTime('2023-05-09 00:00:00.000000'))",
        )

    def test_date_range_with_timezone(self):
        self.team.timezone = "Europe/Berlin"

        self.assertEqual(
            self._get_date_where_sql(time_frame="2023-05-08"),
            "greaterOrEquals(timestamp, toDateTime('2023-05-07 22:00:00.000000')), less(timestamp, toDateTime('2023-05-08 22:00:00.000000'))",
        )

    def test_date_range_hourly(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(update={"interval": IntervalType.hour}, deep=True)

        self.assertEqual(
            self._get_date_where_sql(trends_query=trends_query, time_frame="2023-05-08T15:00:00"),
            "greaterOrEquals(timestamp, toDateTime('2023-05-08 13:00:00.000000')), less(timestamp, toDateTime('2023-05-08 14:00:00.000000'))",
        )

    def test_date_range_compare_previous(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(update={"trendsFilter": TrendsFilter(compare=True)}, deep=True)

        self.assertEqual(
            self._get_date_where_sql(trends_query=trends_query, time_frame="2023-05-10", compare_value=Compare.current),
            "greaterOrEquals(timestamp, toDateTime('2023-05-09 22:00:00.000000')), less(timestamp, toDateTime('2023-05-10 22:00:00.000000'))",
        )
        self.assertEqual(
            self._get_date_where_sql(
                trends_query=trends_query, time_frame="2023-05-10", compare_value=Compare.previous
            ),
            "greaterOrEquals(timestamp, toDateTime('2023-05-02 22:00:00.000000')), less(timestamp, toDateTime('2023-05-03 22:00:00.000000'))",
        )

    def test_date_range_compare_previous_hourly(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(
            update={"trendsFilter": TrendsFilter(compare=True), "interval": IntervalType.hour}, deep=True
        )
        self.assertEqual(
            self._get_date_where_sql(
                trends_query=trends_query, time_frame="2023-05-10T15:00:00", compare_value=Compare.current
            ),
            "greaterOrEquals(timestamp, toDateTime('2023-05-10 13:00:00.000000')), less(timestamp, toDateTime('2023-05-10 14:00:00.000000'))",
        )
        self.assertEqual(
            self._get_date_where_sql(
                trends_query=trends_query, time_frame="2023-05-10T15:00:00", compare_value=Compare.previous
            ),
            "greaterOrEquals(timestamp, toDateTime('2023-05-03 13:00:00.000000')), less(timestamp, toDateTime('2023-05-03 14:00:00.000000'))",
        )

    def test_date_range_total_value(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(
            update={"trendsFilter": TrendsFilter(display=ChartDisplayType.BoldNumber)}, deep=True
        )

        with freeze_time("2022-06-15T12:00:00.000Z"):
            self.assertEqual(
                self._get_date_where_sql(trends_query=trends_query),
                "greaterOrEquals(timestamp, toDateTime('2022-06-07 22:00:00.000000')), lessOrEquals(timestamp, toDateTime('2022-06-15 21:59:59.999999'))",
            )

    def test_date_range_total_value_compare_previous(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(
            update={"trendsFilter": TrendsFilter(display=ChartDisplayType.BoldNumber, compare=True)}, deep=True
        )

        with freeze_time("2022-06-15T12:00:00.000Z"):
            self.assertEqual(
                self._get_date_where_sql(trends_query=trends_query, compare_value=Compare.current),
                "greaterOrEquals(timestamp, toDateTime('2022-06-07 22:00:00.000000')), lessOrEquals(timestamp, toDateTime('2022-06-15 21:59:59.999999'))",
            )
            self.assertEqual(
                self._get_date_where_sql(trends_query=trends_query, compare_value=Compare.previous),
                "greaterOrEquals(timestamp, toDateTime('2022-05-31 22:00:00.000000')), lessOrEquals(timestamp, toDateTime('2022-06-08 21:59:59.999999'))",
            )

    def test_date_range_weekly_active_users_math(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(
            update={"series": [EventsNode(event="$pageview", math=BaseMathType.weekly_active)]}, deep=True
        )

        with freeze_time("2024-05-30T12:00:00.000Z"):
            self.assertEqual(
                self._get_date_where_sql(trends_query=trends_query, time_frame="2024-05-27"),
                "greaterOrEquals(timestamp, minus(toDateTime('2024-05-26 22:00:00.000000'), toIntervalDay(6))), less(timestamp, toDateTime('2024-05-27 22:00:00.000000'))",
            )

    def test_date_range_weekly_active_users_math_compare_previous(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(
            update={
                "series": [EventsNode(event="$pageview", math=BaseMathType.weekly_active)],
                "trendsFilter": TrendsFilter(compare=True),
            },
            deep=True,
        )

        with freeze_time("2024-05-30T12:00:00.000Z"):
            self.assertEqual(
                self._get_date_where_sql(
                    trends_query=trends_query, time_frame="2024-05-27", compare_value=Compare.current
                ),
                "greaterOrEquals(timestamp, minus(toDateTime('2024-05-26 22:00:00.000000'), toIntervalDay(6))), less(timestamp, toDateTime('2024-05-27 22:00:00.000000'))",
            )
            self.assertEqual(
                self._get_date_where_sql(
                    trends_query=trends_query, time_frame="2024-05-27", compare_value=Compare.previous
                ),
                "greaterOrEquals(timestamp, minus(toDateTime('2024-05-19 22:00:00.000000'), toIntervalDay(6))), less(timestamp, toDateTime('2024-05-20 22:00:00.000000'))",
            )

    def test_date_range_weekly_active_users_math_total_value(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(
            update={
                "series": [EventsNode(event="$pageview", math=BaseMathType.weekly_active)],
                "trendsFilter": TrendsFilter(display=ChartDisplayType.BoldNumber),
            },
            deep=True,
        )

        with freeze_time("2024-05-30T12:00:00.000Z"):
            self.assertEqual(
                self._get_date_where_sql(trends_query=trends_query),
                "greaterOrEquals(timestamp, minus(toDateTime('2024-05-30 21:59:59.999999'), toIntervalDay(6))), lessOrEquals(timestamp, toDateTime('2024-05-30 21:59:59.999999'))",
            )

    def test_date_range_weekly_active_users_math_total_value_compare_previous(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(
            update={
                "series": [EventsNode(event="$pageview", math=BaseMathType.weekly_active)],
                "trendsFilter": TrendsFilter(compare=True, display=ChartDisplayType.BoldNumber),
            },
            deep=True,
        )

        with freeze_time("2024-05-30T12:00:00.000Z"):
            self.assertEqual(
                self._get_date_where_sql(trends_query=trends_query, compare_value=Compare.previous),
                "greaterOrEquals(timestamp, minus(toDateTime('2024-05-23 21:59:59.999999'), toIntervalDay(6))), lessOrEquals(timestamp, toDateTime('2024-05-23 21:59:59.999999'))",
            )

    def test_date_range_monthly_active_users_math(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(
            update={"series": [EventsNode(event="$pageview", math=BaseMathType.monthly_active)]}, deep=True
        )

        with freeze_time("2024-05-30T12:00:00.000Z"):
            self.assertEqual(
                self._get_date_where_sql(trends_query=trends_query, time_frame="2024-05-27"),
                "greaterOrEquals(timestamp, minus(toDateTime('2024-05-26 22:00:00.000000'), toIntervalDay(29))), less(timestamp, toDateTime('2024-05-27 22:00:00.000000'))",
            )

    def test_date_range_explicit_date_from(self):
        self.team.timezone = "Europe/Berlin"

        trends_query = default_query.model_copy(
            update={"dateRange": DateRange(date_from="2024-05-08T14:29:13.634000Z", date_to=None, explicitDate=True)},
            deep=True,
        )
        with freeze_time("2024-05-08T15:32:00.000Z"):
            self.assertEqual(
                self._get_date_where_sql(trends_query=trends_query, time_frame="2024-05-08"),
                "greaterOrEquals(timestamp, toDateTime('2024-05-08 14:29:13.634000')), lessOrEquals(timestamp, toDateTime('2024-05-08 15:32:00.000000'))",
            )

    def test_date_range_explicit_date_to(self):
        trends_query = default_query.model_copy(
            update={
                "dateRange": DateRange(
                    date_from="2024-05-08T14:29:13.634000Z", date_to="2024-05-08T14:32:57.692000Z", explicitDate=True
                )
            },
            deep=True,
        )
        with freeze_time("2024-05-08T15:32:00.000Z"):
            self.assertEqual(
                self._get_date_where_sql(trends_query=trends_query, time_frame="2024-05-08"),
                "greaterOrEquals(timestamp, toDateTime('2024-05-08 14:29:13.634000')), lessOrEquals(timestamp, toDateTime('2024-05-08 14:32:57.692000'))",
            )

    def test_date_range_explicit_monthly_active_users_math(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(
            update={
                "series": [EventsNode(event="$pageview", math=BaseMathType.monthly_active)],
                "dateRange": DateRange(
                    date_from="2024-05-08T14:29:13.634000Z", date_to="2024-05-08T14:32:57.692000Z", explicitDate=True
                ),
            },
            deep=True,
        )
        with freeze_time("2024-05-08T15:32:00.000Z"):
            self.assertEqual(
                self._get_date_where_sql(trends_query=trends_query, time_frame="2024-05-08"),
                "greaterOrEquals(timestamp, greatest(minus(toDateTime('2024-05-07 22:00:00.000000'), toIntervalDay(29)), toDateTime('2024-05-08 14:29:13.634000'))), less(timestamp, least(toDateTime('2024-05-08 22:00:00.000000'), toDateTime('2024-05-08 14:32:57.692000')))",
            )
