from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import patch

from posthog.schema import DateRange, EventPropertyFilter, PropertyOperator, WebStatsBreakdown, WebStatsTableQuery

from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner


class TestEventsPrefilterTransformer(ClickhouseTestMixin, APIBaseTest):
    def _run_prefiltered_query(self, **query_kwargs):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[],
            breakdownBy=WebStatsBreakdown.PAGE,
            **query_kwargs,
        )
        with patch(
            "posthog.hogql_queries.web_analytics.stats_table.is_web_analytics_events_prefilter_team",
            return_value=True,
        ):
            runner = WebStatsTableQueryRunner(team=self.team, query=query)
            runner.calculate()
            return runner.paginator.response.clickhouse or ""

    def test_bounce_query_wraps_from_events(self):
        sql = self._run_prefiltered_query(includeBounceRate=True)

        assert "toDate(events.timestamp)" in sql
        assert sql.count("toDate(events.timestamp)") >= 2  # at least one FROM events wrapped

    def test_avg_time_query_wraps_from_events(self):
        sql = self._run_prefiltered_query(includeAvgTimeOnPage=True)

        assert "toDate(events.timestamp)" in sql

    def test_prefilter_includes_team_id(self):
        sql = self._run_prefiltered_query(includeBounceRate=True)

        assert f"equals(events.team_id, {self.team.pk})" in sql

    def test_prefilter_date_bounds_have_buffer(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[],
            breakdownBy=WebStatsBreakdown.PAGE,
            includeBounceRate=True,
        )
        with patch(
            "posthog.hogql_queries.web_analytics.stats_table.is_web_analytics_events_prefilter_team",
            return_value=True,
        ):
            runner = WebStatsTableQueryRunner(team=self.team, query=query)
            date_from, date_to = runner._events_prefilter_date_bounds()

        # Date range is Jan 1-31, buffer is ±1 day
        assert date_from == "2023-12-31"
        assert date_to == "2024-02-01"

    def test_prefilter_with_event_filter(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[
                EventPropertyFilter(
                    key="$geoip_city_name",
                    operator=PropertyOperator.EXACT,
                    value=["Pretoria"],
                )
            ],
            breakdownBy=WebStatsBreakdown.PAGE,
            includeBounceRate=True,
        )
        with patch(
            "posthog.hogql_queries.web_analytics.stats_table.is_web_analytics_events_prefilter_team",
            return_value=True,
        ):
            runner = WebStatsTableQueryRunner(team=self.team, query=query)
            runner.calculate()
            sql = runner.paginator.response.clickhouse or ""

        assert "toDate(events.timestamp)" in sql

    def test_non_prefiltered_team_unchanged(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[],
            breakdownBy=WebStatsBreakdown.PAGE,
            includeBounceRate=True,
        )
        with patch(
            "posthog.hogql_queries.web_analytics.stats_table.is_web_analytics_events_prefilter_team",
            return_value=False,
        ):
            runner = WebStatsTableQueryRunner(team=self.team, query=query)
            runner.calculate()
            sql = runner.paginator.response.clickhouse or ""

        assert "toDate(events.timestamp)" not in sql

    def test_main_query_without_bounce_not_affected(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-31"),
            properties=[],
            breakdownBy=WebStatsBreakdown.DEVICE_TYPE,
        )
        with patch(
            "posthog.hogql_queries.web_analytics.stats_table.is_web_analytics_events_prefilter_team",
            return_value=True,
        ):
            runner = WebStatsTableQueryRunner(team=self.team, query=query)
            runner.calculate()
            sql = runner.paginator.response.clickhouse or ""

        # Non-bounce queries also get wrapped since they go through the same _calculate path
        assert "toDate(events.timestamp)" in sql
