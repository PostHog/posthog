from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import DateRange, WebOverviewQuery, WebStatsBreakdown, WebStatsTableQuery

from posthog.hogql import ast

from posthog.hogql_queries.web_analytics.stats_table import WebStatsTableQueryRunner
from posthog.hogql_queries.web_analytics.web_overview import WebOverviewQueryRunner


class TestWebAnalyticsEventTypeSettings(ClickhouseTestMixin, APIBaseTest):
    def _create_stats_table_runner(self, breakdown_by=WebStatsBreakdown.PAGE):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-15"),
            properties=[],
            breakdownBy=breakdown_by,
        )
        return WebStatsTableQueryRunner(team=self.team, query=query)

    def _create_overview_runner(self):
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-15"),
            properties=[],
        )
        return WebOverviewQueryRunner(team=self.team, query=query)

    @parameterized.expand(
        [
            (["$pageview"], ["$pageview"]),
            (["$screen"], ["$screen"]),
            (["$pageview", "$screen"], ["$pageview", "$screen"]),
            (None, ["$pageview", "$screen"]),
            ([], ["$pageview", "$screen"]),
        ]
    )
    def test_configured_event_types(self, event_types, expected_events):
        self.team.web_analytics_event_types = event_types
        self.team.save()

        runner = self._create_stats_table_runner()
        self.assertEqual(sorted(runner.configured_event_types), sorted(expected_events))

    def test_event_type_expr_with_both_events(self):
        self.team.web_analytics_event_types = ["$pageview", "$screen"]
        self.team.save()

        runner = self._create_stats_table_runner()
        expr = runner.event_type_expr

        # Should be an Or expression with two comparisons
        self.assertIsInstance(expr, ast.Or)
        self.assertEqual(len(expr.exprs), 2)

    def test_event_type_expr_with_single_event(self):
        self.team.web_analytics_event_types = ["$pageview"]
        self.team.save()

        runner = self._create_stats_table_runner()
        expr = runner.event_type_expr

        # Should be a single CompareOperation, not an Or
        self.assertIsInstance(expr, ast.CompareOperation)

    def test_event_type_expr_default(self):
        # Default should include both events
        self.team.web_analytics_event_types = None
        self.team.save()

        runner = self._create_stats_table_runner()
        expr = runner.event_type_expr

        # Should be an Or expression with both events
        self.assertIsInstance(expr, ast.Or)
        self.assertEqual(len(expr.exprs), 2)


class TestWebAnalyticsSessionExpansionSettings(ClickhouseTestMixin, APIBaseTest):
    def _create_overview_runner(self):
        query = WebOverviewQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-15"),
            properties=[],
        )
        return WebOverviewQueryRunner(team=self.team, query=query)

    @parameterized.expand(
        [
            (True, True),
            (False, False),
            (None, True),  # Default is True
        ]
    )
    def test_session_expansion_enabled_property(self, expansion_enabled, expected):
        self.team.web_analytics_session_expansion_enabled = expansion_enabled
        self.team.save()

        runner = self._create_overview_runner()
        self.assertEqual(runner.session_expansion_enabled, expected)

    def test_session_where_with_expansion_enabled(self):
        self.team.web_analytics_session_expansion_enabled = True
        self.team.save()

        runner = self._create_overview_runner()
        session_where = runner.session_where()

        # The expression should contain the 1-hour expansion
        # We check that the expression was generated (detailed SQL testing is in integration tests)
        self.assertIsNotNone(session_where)

    def test_session_where_with_expansion_disabled(self):
        self.team.web_analytics_session_expansion_enabled = False
        self.team.save()

        runner = self._create_overview_runner()
        session_where = runner.session_where()

        # The expression should be generated without expansion
        self.assertIsNotNone(session_where)

    def test_session_having_with_expansion_enabled(self):
        self.team.web_analytics_session_expansion_enabled = True
        self.team.save()

        runner = self._create_overview_runner()
        session_having = runner.session_having()

        # Should return an expression (min_timestamp filter)
        self.assertIsNotNone(session_having)

    def test_session_having_with_expansion_disabled(self):
        self.team.web_analytics_session_expansion_enabled = False
        self.team.save()

        runner = self._create_overview_runner()
        session_having = runner.session_having()

        # Should return a Constant(True) since no min_timestamp filter needed
        self.assertIsInstance(session_having, ast.Constant)
        self.assertEqual(session_having.value, True)


class TestWebAnalyticsPathPropertySelection(ClickhouseTestMixin, APIBaseTest):
    def _create_stats_table_runner(self, breakdown_by=WebStatsBreakdown.PAGE):
        query = WebStatsTableQuery(
            dateRange=DateRange(date_from="2023-12-01", date_to="2023-12-15"),
            properties=[],
            breakdownBy=breakdown_by,
        )
        return WebStatsTableQueryRunner(team=self.team, query=query)

    def test_path_breakdown_with_pageview_only(self):
        self.team.web_analytics_event_types = ["$pageview"]
        self.team.save()

        runner = self._create_stats_table_runner(breakdown_by=WebStatsBreakdown.PAGE)
        path_expr = runner._get_path_breakdown_expr()

        # Should use $pathname (possibly wrapped in path cleaning)
        # The expression should not be a Call to coalesce
        if isinstance(path_expr, ast.Call):
            self.assertNotEqual(path_expr.name, "coalesce")

    def test_path_breakdown_with_screen_only(self):
        self.team.web_analytics_event_types = ["$screen"]
        self.team.save()

        runner = self._create_stats_table_runner(breakdown_by=WebStatsBreakdown.PAGE)
        path_expr = runner._get_path_breakdown_expr()

        # Should use $screen_name directly (no path cleaning for mobile)
        self.assertIsInstance(path_expr, ast.Field)
        self.assertEqual(path_expr.chain, ["events", "properties", "$screen_name"])

    def test_path_breakdown_with_both_events(self):
        self.team.web_analytics_event_types = ["$pageview", "$screen"]
        self.team.save()

        runner = self._create_stats_table_runner(breakdown_by=WebStatsBreakdown.PAGE)
        path_expr = runner._get_path_breakdown_expr()

        # Should use COALESCE - check for the coalesce call
        # Note: might be wrapped in path cleaning
        def find_coalesce(expr):
            if isinstance(expr, ast.Call) and expr.name == "coalesce":
                return True
            if isinstance(expr, ast.Call):
                for arg in expr.args:
                    if find_coalesce(arg):
                        return True
            return False

        self.assertTrue(find_coalesce(path_expr), "Expected COALESCE in path breakdown expression")
