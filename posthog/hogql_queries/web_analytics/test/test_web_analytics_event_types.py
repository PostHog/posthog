from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import DateRange, WebStatsBreakdown, WebStatsTableQuery

from posthog.hogql.printer import to_printed_hogql

from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner


class TestWebAnalyticsEventTypes(ClickhouseTestMixin, APIBaseTest):
    """Tests for the event types configuration feature."""

    def _create_stats_table_runner(self, breakdown_by=WebStatsBreakdown.PAGE):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-07"),
            properties=[],
            breakdownBy=breakdown_by,
        )
        return WebStatsTableQueryRunner(team=self.team, query=query)

    @parameterized.expand(
        [
            ("both_types_default", None, ["$pageview", "$screen"]),
            ("both_types_explicit", ["$pageview", "$screen"], ["$pageview", "$screen"]),
            ("pageview_only", ["$pageview"], ["$pageview"]),
            ("screen_only", ["$screen"], ["$screen"]),
            ("empty_list_defaults_to_both", [], ["$pageview", "$screen"]),
        ]
    )
    def test_configured_event_types(self, _name, setting_value, expected_types):
        self.team.web_analytics_event_types = setting_value
        self.team.save()

        runner = self._create_stats_table_runner()

        self.assertEqual(runner.configured_event_types, expected_types)


class TestWebAnalyticsPathPropertySelection(ClickhouseTestMixin, APIBaseTest):
    """Tests for path property selection based on configured event types."""

    def _create_stats_table_runner(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-07"),
            properties=[],
            breakdownBy=WebStatsBreakdown.PAGE,
        )
        return WebStatsTableQueryRunner(team=self.team, query=query)

    def test_both_event_types_uses_coalesce(self):
        self.team.web_analytics_event_types = ["$pageview", "$screen"]
        self.team.save()

        runner = self._create_stats_table_runner()
        query = runner.to_query()
        sql = to_printed_hogql(query, team=self.team)

        # Should use coalesce($pathname, $screen_name)
        self.assertIn("coalesce", sql.lower())
        self.assertIn("$pathname", sql)
        self.assertIn("$screen_name", sql)

    def test_pageview_only_uses_pathname(self):
        self.team.web_analytics_event_types = ["$pageview"]
        self.team.save()

        runner = self._create_stats_table_runner()
        query = runner.to_query()
        sql = to_printed_hogql(query, team=self.team)

        # Should use $pathname only (no coalesce, no $screen_name)
        self.assertIn("$pathname", sql)
        self.assertNotIn("$screen_name", sql)

    def test_screen_only_uses_screen_name(self):
        self.team.web_analytics_event_types = ["$screen"]
        self.team.save()

        runner = self._create_stats_table_runner()
        query = runner.to_query()
        sql = to_printed_hogql(query, team=self.team)

        # Should use $screen_name only (no $pathname in breakdown context)
        self.assertIn("$screen_name", sql)


class TestWebAnalyticsEventTypeExpr(ClickhouseTestMixin, APIBaseTest):
    """Tests for event_type_expr based on configured event types."""

    def _create_stats_table_runner(self):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2024-01-01", date_to="2024-01-07"),
            properties=[],
            breakdownBy=WebStatsBreakdown.PAGE,
        )
        return WebStatsTableQueryRunner(team=self.team, query=query)

    def test_both_event_types_in_query(self):
        self.team.web_analytics_event_types = ["$pageview", "$screen"]
        self.team.save()

        runner = self._create_stats_table_runner()
        query = runner.to_query()
        sql = to_printed_hogql(query, team=self.team)

        # Both event types should be in the SQL
        self.assertIn("$pageview", sql)
        self.assertIn("$screen", sql)

    def test_single_event_type_in_query(self):
        self.team.web_analytics_event_types = ["$pageview"]
        self.team.save()

        runner = self._create_stats_table_runner()
        query = runner.to_query()
        sql = to_printed_hogql(query, team=self.team)

        # Only $pageview should be in the event filter
        self.assertIn("$pageview", sql)
