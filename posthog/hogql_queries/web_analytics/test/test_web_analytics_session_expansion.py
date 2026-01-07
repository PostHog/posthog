from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import DateRange, WebOverviewQuery, WebStatsBreakdown, WebStatsTableQuery

from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner


class TestWebAnalyticsSessionExpansion(ClickhouseTestMixin, APIBaseTest):
    """Tests for the session expansion toggle feature."""

    def _create_stats_table_runner(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-07"),
            properties=[],
            breakdownBy=WebStatsBreakdown.PAGE,
        )
        return WebStatsTableQueryRunner(team=self.team, query=query)

    def _create_overview_runner(self):
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-07"),
            properties=[],
        )
        return WebOverviewQueryRunner(team=self.team, query=query)

    @parameterized.expand(
        [
            ("enabled_true", True, True, "min(session.$start_timestamp)"),
            ("enabled_false", False, False, "min(events.timestamp)"),
            ("enabled_none_defaults_to_true", None, True, "min(session.$start_timestamp)"),
        ]
    )
    def test_stats_table_session_expansion_enabled(self, _name, setting_value, expected_enabled, expected_expr):
        self.team.web_analytics_session_expansion_enabled = setting_value
        self.team.save()

        runner = self._create_stats_table_runner()

        self.assertEqual(runner.session_expansion_enabled, expected_enabled)
        self.assertEqual(runner.start_timestamp_expr, expected_expr)

    @parameterized.expand(
        [
            ("enabled_true", True, True, "min(session.$start_timestamp)"),
            ("enabled_false", False, False, "min(events.timestamp)"),
            ("enabled_none_defaults_to_true", None, True, "min(session.$start_timestamp)"),
        ]
    )
    def test_overview_session_expansion_enabled(self, _name, setting_value, expected_enabled, expected_expr):
        self.team.web_analytics_session_expansion_enabled = setting_value
        self.team.save()

        runner = self._create_overview_runner()

        self.assertEqual(runner.session_expansion_enabled, expected_enabled)
        self.assertEqual(runner.start_timestamp_expr, expected_expr)

    def test_stats_table_generates_correct_sql_when_expansion_disabled(self):
        self.team.web_analytics_session_expansion_enabled = False
        self.team.save()

        runner = self._create_stats_table_runner()
        query = runner.to_query()

        from posthog.hogql.printer import to_printed_hogql

        sql = to_printed_hogql(query, team=self.team)

        # Verify the SQL uses events.timestamp instead of session.$start_timestamp
        self.assertIn("min(events.timestamp)", sql)
        self.assertNotIn("min(session.$start_timestamp)", sql)

    def test_stats_table_generates_correct_sql_when_expansion_enabled(self):
        self.team.web_analytics_session_expansion_enabled = True
        self.team.save()

        runner = self._create_stats_table_runner()
        query = runner.to_query()

        from posthog.hogql.printer import to_printed_hogql

        sql = to_printed_hogql(query, team=self.team)

        # Verify the SQL uses session.$start_timestamp
        self.assertIn("min(session.$start_timestamp)", sql)
        self.assertNotIn("min(events.timestamp)", sql)
