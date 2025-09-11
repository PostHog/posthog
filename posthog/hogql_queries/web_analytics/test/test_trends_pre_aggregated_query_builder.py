from datetime import UTC, datetime
from typing import Optional, cast

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock

from posthog.schema import HogQLQueryModifiers, IntervalType, WebTrendsMetric, WebTrendsQuery

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import print_ast

from posthog.hogql_queries.web_analytics.trends_pre_aggregated_query_builder import TrendsPreAggregatedQueryBuilder


class TestTrendsPreAggregatedQueryBuilder(ClickhouseTestMixin, APIBaseTest):
    def _create_mock_runner(self, query: WebTrendsQuery, modifiers: Optional[HogQLQueryModifiers] = None):
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
        query = WebTrendsQuery(metrics=[], interval=IntervalType.DAY, properties=[])
        runner = self._create_mock_runner(query)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        # Test unique users metric
        unique_users_expr = builder._get_metric_expr(WebTrendsMetric.UNIQUE_USERS)
        self.assertEqual(unique_users_expr.alias, "unique_users")
        self.assertIsInstance(unique_users_expr.expr, ast.Call)

        unique_call = cast(ast.Call, unique_users_expr.expr)
        self.assertEqual(unique_call.name, "uniqMerge")
        self.assertEqual(len(unique_call.args), 1)
        self.assertIsInstance(unique_call.args[0], ast.Field)
        unique_field = cast(ast.Field, unique_call.args[0])
        self.assertEqual(unique_field.chain, ["persons_uniq_state"])

        # Test page views metric
        page_views_expr = builder._get_metric_expr(WebTrendsMetric.PAGE_VIEWS)
        self.assertEqual(page_views_expr.alias, "page_views")
        self.assertIsInstance(page_views_expr.expr, ast.Call)
        page_call = cast(ast.Call, page_views_expr.expr)
        self.assertEqual(page_call.name, "sumMerge")

        # Test sessions metric
        sessions_expr = builder._get_metric_expr(WebTrendsMetric.SESSIONS)
        self.assertEqual(sessions_expr.alias, "sessions")
        self.assertIsInstance(sessions_expr.expr, ast.Call)
        sessions_call = cast(ast.Call, sessions_expr.expr)
        self.assertEqual(sessions_call.name, "uniqMerge")
        self.assertIsInstance(sessions_call.args[0], ast.Field)
        sessions_field = cast(ast.Field, sessions_call.args[0])
        self.assertEqual(sessions_field.chain, ["sessions_uniq_state"])

        # Test bounces metric
        bounces_expr = builder._get_metric_expr(WebTrendsMetric.BOUNCES)
        self.assertEqual(bounces_expr.alias, "bounces")
        self.assertIsInstance(bounces_expr.expr, ast.Call)
        bounces_call = cast(ast.Call, bounces_expr.expr)
        self.assertEqual(bounces_call.name, "sumMerge")
        self.assertIsInstance(bounces_call.args[0], ast.Field)
        bounces_field = cast(ast.Field, bounces_call.args[0])
        self.assertEqual(bounces_field.chain, ["bounces_count_state"])

    def test_get_metric_expr_unknown_metric_raises_error(self):
        query = WebTrendsQuery(metrics=[], interval=IntervalType.DAY, properties=[])
        runner = self._create_mock_runner(query)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        # Test unknown metric raises error
        with self.assertRaises(ValueError) as cm:
            builder._get_metric_expr("unknown_metric")  # type: ignore

        self.assertIn("Unknown metric", str(cm.exception))

    def test_get_metrics_exprs_defaults_to_unique_users(self):
        query = WebTrendsQuery(metrics=[], interval=IntervalType.DAY, properties=[])
        runner = self._create_mock_runner(query)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        metric_exprs = builder._get_metrics_exprs()

        # Should have one metric (default unique users)
        self.assertEqual(len(metric_exprs), 1)
        self.assertEqual(metric_exprs[0].alias, "unique_users")
        self.assertIsInstance(metric_exprs[0].expr, ast.Call)
        call_expr = cast(ast.Call, metric_exprs[0].expr)
        self.assertEqual(call_expr.name, "uniqMerge")

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
