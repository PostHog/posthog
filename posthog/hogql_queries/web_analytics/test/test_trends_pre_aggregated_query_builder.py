from typing import Optional
from unittest.mock import MagicMock

from posthog.hogql_queries.web_analytics.trends_pre_aggregated_query_builder import TrendsPreAggregatedQueryBuilder
from posthog.schema import (
    IntervalType,
    HogQLQueryModifiers,
    WebTrendsMetric,
    WebTrendsQuery,
)
from posthog.test.base import (
    APIBaseTest,
    ClickhouseTestMixin,
)
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import print_ast
from datetime import datetime, UTC


class TestTrendsPreAggregatedQueryBuilder(ClickhouseTestMixin, APIBaseTest):
    def _create_mock_runner(self, query: WebTrendsQuery, modifiers: Optional[HogQLQueryModifiers] = None):
        """Helper to create a mock query runner with the specified query and modifiers"""

        runner = MagicMock()
        runner.query = query
        runner.team = self.team
        runner.modifiers = modifiers or HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=True, convertToProjectTimezone=False
        )

        mock_date_range = MagicMock()
        mock_date_range.date_from.return_value = datetime(2025, 1, 1, tzinfo=UTC)
        mock_date_range.date_to.return_value = datetime(2025, 1, 31, tzinfo=UTC)

        runner.query_date_range = mock_date_range
        runner.query_compare_to_date_range = None

        return runner

    def test_basic_query_structure_single_metric(self):
        """Test basic AST structure for a single metric"""
        query = WebTrendsQuery(
            interval=IntervalType.DAY,
            metrics=[WebTrendsMetric.UNIQUE_USERS],
            properties=[],
        )

        runner = self._create_mock_runner(query)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        ast_query = builder.get_query()
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        hogql_query = print_ast(ast_query, context=context, dialect="hogql")

        # Verify the query structure
        self.assertIn("SELECT", hogql_query)
        self.assertIn("toStartOfDay(period_bucket) AS bucket", hogql_query)
        self.assertIn("uniqMerge(persons_uniq_state) AS unique_users", hogql_query)
        self.assertIn("FROM web_bounces_combined", hogql_query)
        self.assertIn("GROUP BY bucket", hogql_query)
        self.assertIn("ORDER BY bucket ASC", hogql_query)

    def test_multiple_metrics(self):
        """Test query with multiple metrics"""
        query = WebTrendsQuery(
            interval=IntervalType.DAY,
            metrics=[
                WebTrendsMetric.UNIQUE_USERS,
                WebTrendsMetric.PAGE_VIEWS,
                WebTrendsMetric.SESSIONS,
                WebTrendsMetric.BOUNCES,
            ],
            properties=[],
        )

        runner = self._create_mock_runner(query)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        ast_query = builder.get_query()
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        hogql_query = print_ast(ast_query, context=context, dialect="hogql")

        # Verify all metrics are included
        self.assertIn("uniqMerge(persons_uniq_state) AS unique_users", hogql_query)
        self.assertIn("sumMerge(pageviews_count_state) AS page_views", hogql_query)
        self.assertIn("uniqMerge(sessions_uniq_state) AS sessions", hogql_query)
        self.assertIn("sumMerge(bounces_count_state) AS bounces", hogql_query)

    def test_weekly_interval(self):
        """Test query with weekly interval"""
        query = WebTrendsQuery(
            interval=IntervalType.WEEK,
            metrics=[WebTrendsMetric.UNIQUE_USERS],
            properties=[],
        )

        runner = self._create_mock_runner(query)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        ast_query = builder.get_query()
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        hogql_query = print_ast(ast_query, context=context, dialect="hogql")

        # Verify weekly interval function is used
        self.assertIn("toStartOfWeek(period_bucket) AS bucket", hogql_query)

    def test_monthly_interval(self):
        """Test query with monthly interval"""
        query = WebTrendsQuery(
            interval=IntervalType.MONTH,
            metrics=[WebTrendsMetric.UNIQUE_USERS],
            properties=[],
        )

        runner = self._create_mock_runner(query)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        ast_query = builder.get_query()
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        hogql_query = print_ast(ast_query, context=context, dialect="hogql")

        # Verify monthly interval function is used
        self.assertIn("toStartOfMonth(period_bucket) AS bucket", hogql_query)

    def test_session_metrics(self):
        """Test session duration and total session count metrics"""
        query = WebTrendsQuery(
            metrics=[
                WebTrendsMetric.SESSION_DURATION,
                WebTrendsMetric.TOTAL_SESSIONS,
            ],
            interval=IntervalType.DAY,
            properties=[],
        )

        runner = self._create_mock_runner(query)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        ast_query = builder.get_query()
        context = HogQLContext(team_id=self.team.pk, enable_select_queries=True)
        hogql_query = print_ast(ast_query, context=context, dialect="hogql")

        # Verify session metrics are included
        self.assertIn("sumMerge(total_session_duration_state) AS session_duration", hogql_query)
        self.assertIn("sumMerge(total_session_count_state) AS total_sessions", hogql_query)

    def test_can_use_preaggregated_tables_valid(self):
        """Test validation allows supported configurations"""
        query = WebTrendsQuery(interval=IntervalType.DAY, metrics=[WebTrendsMetric.UNIQUE_USERS], properties=[])

        modifiers = HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=True,
            convertToProjectTimezone=False,  # Required for pre-aggregated
        )

        runner = self._create_mock_runner(query, modifiers)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        # Should be valid
        self.assertTrue(builder.can_use_preaggregated_tables())

    def test_can_use_preaggregated_tables_rejects_timezone_conversion(self):
        """Test validation rejects queries with timezone conversion"""
        query = WebTrendsQuery(
            interval=IntervalType.DAY,
            metrics=[WebTrendsMetric.UNIQUE_USERS],
            properties=[],
        )

        modifiers = HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=True,
            convertToProjectTimezone=True,  # This should be rejected
        )

        runner = self._create_mock_runner(query, modifiers)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        # Should reject because convertToProjectTimezone=True
        self.assertFalse(builder.can_use_preaggregated_tables())

    def test_can_use_preaggregated_tables_rejects_unsupported_interval(self):
        """Test validation rejects unsupported intervals"""
        query = WebTrendsQuery(
            interval=IntervalType.HOUR,  # Unsupported
            metrics=[WebTrendsMetric.UNIQUE_USERS],
            properties=[],
        )

        runner = self._create_mock_runner(query)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        # Should reject because HOUR interval is not supported
        self.assertFalse(builder.can_use_preaggregated_tables())

    def test_get_metric_expr_individual_metrics(self):
        """Test individual metric AST expressions are correct"""
        query = WebTrendsQuery(metrics=[], interval=IntervalType.DAY, properties=[])
        runner = self._create_mock_runner(query)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        # Test unique users metric
        unique_users_expr = builder._get_metric_expr(WebTrendsMetric.UNIQUE_USERS)
        self.assertEqual(unique_users_expr.alias, "unique_users")
        self.assertEqual(unique_users_expr.expr.name, "uniqMerge")
        self.assertEqual(len(unique_users_expr.expr.args), 1)
        self.assertEqual(unique_users_expr.expr.args[0].chain, ["persons_uniq_state"])

        # Test page views metric
        page_views_expr = builder._get_metric_expr(WebTrendsMetric.PAGE_VIEWS)
        self.assertEqual(page_views_expr.alias, "page_views")
        self.assertEqual(page_views_expr.expr.name, "sumMerge")
        self.assertEqual(unique_users_expr.expr.args[0].chain, ["persons_uniq_state"])

        # Test sessions metric
        sessions_expr = builder._get_metric_expr(WebTrendsMetric.SESSIONS)
        self.assertEqual(sessions_expr.alias, "sessions")
        self.assertEqual(sessions_expr.expr.name, "uniqMerge")
        self.assertEqual(sessions_expr.expr.args[0].chain, ["sessions_uniq_state"])

        # Test bounces metric
        bounces_expr = builder._get_metric_expr(WebTrendsMetric.BOUNCES)
        self.assertEqual(bounces_expr.alias, "bounces")
        self.assertEqual(bounces_expr.expr.name, "sumMerge")
        self.assertEqual(bounces_expr.expr.args[0].chain, ["bounces_count_state"])

    def test_get_metric_expr_unknown_metric_raises_error(self):
        """Test that unknown metric raises ValueError"""
        query = WebTrendsQuery(metrics=[], interval=IntervalType.DAY, properties=[])
        runner = self._create_mock_runner(query)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        # Test unknown metric raises error
        with self.assertRaises(ValueError) as cm:
            builder._get_metric_expr("unknown_metric")  # type: ignore

        self.assertIn("Unknown metric", str(cm.exception))

    def test_get_metrics_exprs_defaults_to_unique_users(self):
        """Test that _get_metrics_exprs defaults to unique users when no metrics specified"""
        query = WebTrendsQuery(metrics=[], interval=IntervalType.DAY, properties=[])
        runner = self._create_mock_runner(query)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        metric_exprs = builder._get_metrics_exprs()

        # Should have one metric (default unique users)
        self.assertEqual(len(metric_exprs), 1)
        self.assertEqual(metric_exprs[0].alias, "unique_users")
        self.assertEqual(metric_exprs[0].expr.name, "uniqMerge")

    def test_get_interval_function_mappings(self):
        query = WebTrendsQuery(metrics=[], interval=IntervalType.DAY, properties=[])
        runner = self._create_mock_runner(query)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        # Test day interval
        runner.query.interval = IntervalType.DAY
        self.assertEqual(builder._get_interval_function(), "toStartOfDay")

        # Test week interval
        runner.query.interval = IntervalType.WEEK
        self.assertEqual(builder._get_interval_function(), "toStartOfWeek")

        # Test month interval
        runner.query.interval = IntervalType.MONTH
        self.assertEqual(builder._get_interval_function(), "toStartOfMonth")
