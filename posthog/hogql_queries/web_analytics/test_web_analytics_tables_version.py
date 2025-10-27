from posthog.test.base import APIBaseTest

from posthog.schema import (
    DateRange,
    IntervalType,
    WebOverviewQuery,
    WebStatsBreakdown,
    WebStatsTableQuery,
    WebTrendsMetric,
    WebTrendsQuery,
)

from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner
from posthog.hogql_queries.web_analytics.web_trends_query_runner import WebTrendsQueryRunner


class TestWebAnalyticsTablesVersion(APIBaseTest):
    def test_web_overview_query_runner_uses_team_property(self):
        # Test default behavior (v2 tables)
        query = WebOverviewQuery(dateRange=DateRange(date_from="-7d"), properties=[])
        runner = WebOverviewQueryRunner(query=query, team=self.team)
        self.assertTrue(runner.use_v2_tables)
        self.assertEqual(runner.preaggregated_query_builder.stats_table, "web_pre_aggregated_stats")

        # Test v1 setting
        self.team.web_analytics_pre_aggregated_tables_version = "v1"
        self.team.save()
        runner = WebOverviewQueryRunner(query=query, team=self.team)
        self.assertFalse(runner.use_v2_tables)
        self.assertEqual(runner.preaggregated_query_builder.stats_table, "web_stats_combined")

        # Test v2 setting (explicit)
        self.team.web_analytics_pre_aggregated_tables_version = "v2"
        self.team.save()
        runner = WebOverviewQueryRunner(query=query, team=self.team)
        self.assertTrue(runner.use_v2_tables)
        self.assertEqual(runner.preaggregated_query_builder.stats_table, "web_pre_aggregated_stats")

    def test_web_stats_table_query_runner_uses_team_property(self):
        # Test default behavior (v2 tables)
        query = WebStatsTableQuery(
            breakdownBy=WebStatsBreakdown.PAGE, dateRange=DateRange(date_from="-7d"), properties=[]
        )
        runner = WebStatsTableQueryRunner(query=query, team=self.team)
        self.assertTrue(runner.use_v2_tables)
        self.assertEqual(runner.preaggregated_query_builder.stats_table, "web_pre_aggregated_stats")

        # Test v1 setting
        self.team.web_analytics_pre_aggregated_tables_version = "v1"
        self.team.save()
        runner = WebStatsTableQueryRunner(query=query, team=self.team)
        self.assertFalse(runner.use_v2_tables)
        self.assertEqual(runner.preaggregated_query_builder.stats_table, "web_stats_combined")

    def test_web_trends_query_runner_uses_team_property(self):
        # Test default behavior (v2 tables)
        query = WebTrendsQuery(
            interval=IntervalType.DAY,
            metrics=[WebTrendsMetric.UNIQUE_USERS],
            dateRange=DateRange(date_from="-7d"),
            properties=[],
        )
        runner = WebTrendsQueryRunner(query=query, team=self.team)
        self.assertTrue(runner.use_v2_tables)

        # Test v1 setting
        self.team.web_analytics_pre_aggregated_tables_version = "v1"
        self.team.save()
        runner = WebTrendsQueryRunner(query=query, team=self.team)
        self.assertFalse(runner.use_v2_tables)

        # Test v2 setting (explicit)
        self.team.web_analytics_pre_aggregated_tables_version = "v2"
        self.team.save()
        runner = WebTrendsQueryRunner(query=query, team=self.team)
        self.assertTrue(runner.use_v2_tables)

    def test_backward_compatibility_with_none_value(self):
        # Test that None value defaults to v2 behavior
        self.team.web_analytics_pre_aggregated_tables_version = None
        self.team.save()

        query = WebOverviewQuery(dateRange=DateRange(date_from="-7d"), properties=[])
        runner = WebOverviewQueryRunner(query=query, team=self.team)
        self.assertTrue(runner.use_v2_tables)

    def test_use_v2_tables_parameter_fallback(self):
        # Test that the use_v2_tables parameter still works as fallback
        # when team property is None
        self.team.web_analytics_pre_aggregated_tables_version = None
        self.team.save()

        query = WebOverviewQuery(dateRange=DateRange(date_from="-7d"), properties=[])

        # Test fallback to False
        runner = WebOverviewQueryRunner(query=query, team=self.team, use_v2_tables=False)
        self.assertFalse(runner.use_v2_tables)

        # Test fallback to True
        runner = WebOverviewQueryRunner(query=query, team=self.team, use_v2_tables=True)
        self.assertTrue(runner.use_v2_tables)
