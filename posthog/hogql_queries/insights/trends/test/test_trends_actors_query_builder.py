from datetime import UTC, datetime
from typing import Optional, cast

from freezegun import freeze_time
from posthog.test.base import BaseTest

from hogql_parser import parse_select

from posthog.schema import (
    BaseMathType,
    ChartDisplayType,
    Compare,
    CompareFilter,
    DateRange,
    EventsNode,
    IntervalType,
    MathGroupTypeIndex,
    TrendsFilter,
    TrendsQuery,
)

from posthog.hogql import ast
from posthog.hogql.constants import MAX_SELECT_RETURNED_ROWS
from posthog.hogql.context import HogQLContext
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.printer import prepare_and_print_ast
from posthog.hogql.timings import HogQLTimings

from posthog.constants import UNIQUE_GROUPS
from posthog.hogql_queries.insights.trends.trends_actors_query_builder import TrendsActorsQueryBuilder

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
        sql, _ = prepare_and_print_ast(
            query,
            HogQLContext(team_id=self.team.pk, enable_select_queries=True),
            "hogql",
        )
        return sql[sql.find("WHERE and(") + 10 : sql.find(f") LIMIT {MAX_SELECT_RETURNED_ROWS}")]

    def _get_date_where_sql(self, **kwargs):
        builder = self._get_builder(**kwargs)
        date_expr = builder._date_where_expr()
        return self._print_hogql_expr(list(date_expr))

    def _get_utc_string(self, dt: datetime | None) -> str | None:
        if dt is None:
            return None
        return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%SZ")

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
        trends_query = default_query.model_copy(update={"interval": IntervalType.HOUR}, deep=True)

        self.assertEqual(
            self._get_date_where_sql(trends_query=trends_query, time_frame="2023-05-08T15:00:00"),
            "greaterOrEquals(timestamp, toDateTime('2023-05-08 13:00:00.000000')), less(timestamp, toDateTime('2023-05-08 14:00:00.000000'))",
        )

    def test_date_range_compare_previous(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(update={"compareFilter": CompareFilter(compare=True)}, deep=True)

        self.assertEqual(
            self._get_date_where_sql(trends_query=trends_query, time_frame="2023-05-10", compare_value=Compare.CURRENT),
            "greaterOrEquals(timestamp, toDateTime('2023-05-09 22:00:00.000000')), less(timestamp, toDateTime('2023-05-10 22:00:00.000000'))",
        )
        self.assertEqual(
            self._get_date_where_sql(
                trends_query=trends_query, time_frame="2023-05-10", compare_value=Compare.PREVIOUS
            ),
            "greaterOrEquals(timestamp, toDateTime('2023-05-02 22:00:00.000000')), less(timestamp, toDateTime('2023-05-03 22:00:00.000000'))",
        )

    def test_date_range_compare_previous_hourly(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(
            update={"compareFilter": CompareFilter(compare=True), "interval": IntervalType.HOUR}, deep=True
        )
        self.assertEqual(
            self._get_date_where_sql(
                trends_query=trends_query, time_frame="2023-05-10T15:00:00", compare_value=Compare.CURRENT
            ),
            "greaterOrEquals(timestamp, toDateTime('2023-05-10 13:00:00.000000')), less(timestamp, toDateTime('2023-05-10 14:00:00.000000'))",
        )
        self.assertEqual(
            self._get_date_where_sql(
                trends_query=trends_query, time_frame="2023-05-10T15:00:00", compare_value=Compare.PREVIOUS
            ),
            "greaterOrEquals(timestamp, toDateTime('2023-05-03 13:00:00.000000')), less(timestamp, toDateTime('2023-05-03 14:00:00.000000'))",
        )

    def test_date_range_compare_to(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(
            update={"compareFilter": CompareFilter(compare=True, compare_to="-3d")}, deep=True
        )

        self.assertEqual(
            self._get_date_where_sql(trends_query=trends_query, time_frame="2023-05-10", compare_value=Compare.CURRENT),
            "greaterOrEquals(timestamp, toDateTime('2023-05-09 22:00:00.000000')), less(timestamp, toDateTime('2023-05-10 22:00:00.000000'))",
        )
        self.assertEqual(
            self._get_date_where_sql(
                trends_query=trends_query, time_frame="2023-05-10", compare_value=Compare.PREVIOUS
            ),
            "greaterOrEquals(timestamp, toDateTime('2023-05-06 22:00:00.000000')), less(timestamp, toDateTime('2023-05-07 22:00:00.000000'))",
        )

    def test_date_range_compare_to_hours(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(
            update={"compareFilter": CompareFilter(compare=True, compare_to="-3h")}, deep=True
        )

        self.assertEqual(
            self._get_date_where_sql(trends_query=trends_query, time_frame="2023-05-10", compare_value=Compare.CURRENT),
            "greaterOrEquals(timestamp, toDateTime('2023-05-09 22:00:00.000000')), less(timestamp, toDateTime('2023-05-10 22:00:00.000000'))",
        )
        self.assertEqual(
            self._get_date_where_sql(
                trends_query=trends_query, time_frame="2023-05-10", compare_value=Compare.PREVIOUS
            ),
            "greaterOrEquals(timestamp, toDateTime('2023-05-09 19:00:00.000000')), less(timestamp, toDateTime('2023-05-10 19:00:00.000000'))",
        )

    def test_date_range_total_value(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(
            update={
                "trendsFilter": TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
                "dateRange": DateRange(date_from="-7d", explicitDate=False),
            },
            deep=True,
        )

        with freeze_time("2022-06-15T12:00:00.000Z"):
            self.assertEqual(
                self._get_date_where_sql(trends_query=trends_query),
                "greaterOrEquals(timestamp, toDateTime('2022-06-07 22:00:00.000000')), lessOrEquals(timestamp, toDateTime('2022-06-15 21:59:59.999999'))",
            )

    def test_date_range_total_value_compare_previous(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(
            update={
                "trendsFilter": TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
                "compareFilter": CompareFilter(compare=True),
                "dateRange": DateRange(date_from="-7d", explicitDate=False),
            },
            deep=True,
        )

        with freeze_time("2022-06-15T12:00:00.000Z"):
            self.assertEqual(
                self._get_date_where_sql(trends_query=trends_query, compare_value=Compare.CURRENT),
                "greaterOrEquals(timestamp, toDateTime('2022-06-07 22:00:00.000000')), lessOrEquals(timestamp, toDateTime('2022-06-15 21:59:59.999999'))",
            )
            self.assertEqual(
                self._get_date_where_sql(trends_query=trends_query, compare_value=Compare.PREVIOUS),
                "greaterOrEquals(timestamp, toDateTime('2022-05-31 22:00:00.000000')), lessOrEquals(timestamp, toDateTime('2022-06-08 21:59:59.999999'))",
            )

    def test_date_range_total_value_compare_to(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(
            update={
                "trendsFilter": TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
                "compareFilter": CompareFilter(compare=True, compare_to="-3d"),
                "dateRange": DateRange(date_from="-7d", explicitDate=False),
            },
            deep=True,
        )

        with freeze_time("2022-06-15T12:00:00.000Z"):
            self.assertEqual(
                self._get_date_where_sql(trends_query=trends_query, compare_value=Compare.CURRENT),
                "greaterOrEquals(timestamp, toDateTime('2022-06-07 22:00:00.000000')), lessOrEquals(timestamp, toDateTime('2022-06-15 21:59:59.999999'))",
            )
            self.assertEqual(
                self._get_date_where_sql(trends_query=trends_query, compare_value=Compare.PREVIOUS),
                "greaterOrEquals(timestamp, toDateTime('2022-06-04 22:00:00.000000')), lessOrEquals(timestamp, toDateTime('2022-06-12 21:59:59.999999'))",
            )

    def test_date_range_weekly_active_users_math(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(
            update={"series": [EventsNode(event="$pageview", math=BaseMathType.WEEKLY_ACTIVE)]}, deep=True
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
                "series": [EventsNode(event="$pageview", math=BaseMathType.WEEKLY_ACTIVE)],
                "compareFilter": CompareFilter(compare=True),
            },
            deep=True,
        )

        with freeze_time("2024-05-30T12:00:00.000Z"):
            self.assertEqual(
                self._get_date_where_sql(
                    trends_query=trends_query, time_frame="2024-05-27", compare_value=Compare.CURRENT
                ),
                "greaterOrEquals(timestamp, minus(toDateTime('2024-05-26 22:00:00.000000'), toIntervalDay(6))), less(timestamp, toDateTime('2024-05-27 22:00:00.000000'))",
            )
            self.assertEqual(
                self._get_date_where_sql(
                    trends_query=trends_query, time_frame="2024-05-27", compare_value=Compare.PREVIOUS
                ),
                "greaterOrEquals(timestamp, minus(toDateTime('2024-05-19 22:00:00.000000'), toIntervalDay(6))), less(timestamp, toDateTime('2024-05-20 22:00:00.000000'))",
            )

    def test_date_range_weekly_active_users_math_compare_to(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(
            update={
                "series": [EventsNode(event="$pageview", math=BaseMathType.WEEKLY_ACTIVE)],
                "compareFilter": CompareFilter(compare=True, compare_to="-3d"),
            },
            deep=True,
        )

        with freeze_time("2024-05-30T12:00:00.000Z"):
            self.assertEqual(
                self._get_date_where_sql(
                    trends_query=trends_query, time_frame="2024-05-27", compare_value=Compare.CURRENT
                ),
                "greaterOrEquals(timestamp, minus(toDateTime('2024-05-26 22:00:00.000000'), toIntervalDay(6))), less(timestamp, toDateTime('2024-05-27 22:00:00.000000'))",
            )
            self.assertEqual(
                self._get_date_where_sql(
                    trends_query=trends_query, time_frame="2024-05-27", compare_value=Compare.PREVIOUS
                ),
                "greaterOrEquals(timestamp, minus(toDateTime('2024-05-23 22:00:00.000000'), toIntervalDay(6))), less(timestamp, toDateTime('2024-05-24 22:00:00.000000'))",
            )

    def test_date_range_weekly_active_users_math_total_value(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(
            update={
                "series": [EventsNode(event="$pageview", math=BaseMathType.WEEKLY_ACTIVE)],
                "trendsFilter": TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
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
                "series": [EventsNode(event="$pageview", math=BaseMathType.WEEKLY_ACTIVE)],
                "trendsFilter": TrendsFilter(display=ChartDisplayType.BOLD_NUMBER),
                "compareFilter": CompareFilter(compare=True),
            },
            deep=True,
        )

        with freeze_time("2024-05-30T12:00:00.000Z"):
            self.assertEqual(
                self._get_date_where_sql(trends_query=trends_query, compare_value=Compare.PREVIOUS),
                "greaterOrEquals(timestamp, minus(toDateTime('2024-05-23 21:59:59.999999'), toIntervalDay(6))), lessOrEquals(timestamp, toDateTime('2024-05-23 21:59:59.999999'))",
            )

    def test_date_range_monthly_active_users_math(self):
        self.team.timezone = "Europe/Berlin"
        trends_query = default_query.model_copy(
            update={"series": [EventsNode(event="$pageview", math=BaseMathType.MONTHLY_ACTIVE)]}, deep=True
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
                "series": [EventsNode(event="$pageview", math=BaseMathType.MONTHLY_ACTIVE)],
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

    def test_actor_id_expr_for_groups_math(self):
        maths = [BaseMathType.DAU, UNIQUE_GROUPS, BaseMathType.WEEKLY_ACTIVE, BaseMathType.MONTHLY_ACTIVE]
        for math in maths:
            with self.subTest(math=math):
                trends_query = default_query.model_copy(
                    update={
                        "series": [
                            EventsNode(event="$pageview", math=math, math_group_type_index=MathGroupTypeIndex.NUMBER_0)
                        ]
                    }
                )

                builder = self._get_builder(trends_query=trends_query)

                self.assertEqual(builder._actor_id_expr(), ast.Field(chain=["e", "$group_0"]))
                self.assertIsNone(builder._actor_distinct_id_expr())
                self.assertEqual(
                    builder._filter_empty_actors_expr(),
                    [
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.NotEq,
                            left=ast.Field(chain=["e", "$group_0"]),
                            right=ast.Constant(value=""),
                        )
                    ],
                )
