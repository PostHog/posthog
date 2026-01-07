from datetime import UTC, datetime
from typing import Optional, cast

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock

from posthog.schema import HogQLQueryModifiers, IntervalType, WebTrendsMetric, WebTrendsQuery

from posthog.hogql import ast
from posthog.hogql.context import HogQLContext
from posthog.hogql.printer import prepare_and_print_ast

from posthog.hogql_queries.web_analytics.trends_pre_aggregated_query_builder import TrendsPreAggregatedQueryBuilder
import pytest


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
        hogql_query, _ = prepare_and_print_ast(ast_query, context=context, dialect="hogql")

        # Verify the query structure
        assert "SELECT" in hogql_query
        assert "toStartOfDay(period_bucket) AS bucket" in hogql_query
        assert "uniqMerge(persons_uniq_state) AS unique_users" in hogql_query
        assert "FROM web_bounces_combined" in hogql_query
        assert "GROUP BY bucket" in hogql_query
        assert "ORDER BY bucket ASC" in hogql_query

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
        hogql_query, _ = prepare_and_print_ast(ast_query, context=context, dialect="hogql")

        # Verify all metrics are included
        assert "uniqMerge(persons_uniq_state) AS unique_users" in hogql_query
        assert "sumMerge(pageviews_count_state) AS page_views" in hogql_query
        assert "uniqMerge(sessions_uniq_state) AS sessions" in hogql_query
        assert "sumMerge(bounces_count_state) AS bounces" in hogql_query

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
        hogql_query, _ = prepare_and_print_ast(ast_query, context=context, dialect="hogql")

        # Verify weekly interval function is used
        assert "toStartOfWeek(period_bucket) AS bucket" in hogql_query

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
        hogql_query, _ = prepare_and_print_ast(ast_query, context=context, dialect="hogql")

        # Verify monthly interval function is used
        assert "toStartOfMonth(period_bucket) AS bucket" in hogql_query

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
        hogql_query, _ = prepare_and_print_ast(ast_query, context=context, dialect="hogql")

        # Verify session metrics are included
        assert "sumMerge(total_session_duration_state) AS session_duration" in hogql_query
        assert "sumMerge(total_session_count_state) AS total_sessions" in hogql_query

    def test_can_use_preaggregated_tables_valid(self):
        query = WebTrendsQuery(interval=IntervalType.DAY, metrics=[WebTrendsMetric.UNIQUE_USERS], properties=[])

        modifiers = HogQLQueryModifiers(
            useWebAnalyticsPreAggregatedTables=True,
            convertToProjectTimezone=False,  # Required for pre-aggregated
        )

        runner = self._create_mock_runner(query, modifiers)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        # Should be valid
        assert builder.can_use_preaggregated_tables()

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
        assert not builder.can_use_preaggregated_tables()

    def test_can_use_preaggregated_tables_rejects_unsupported_interval(self):
        query = WebTrendsQuery(
            interval=IntervalType.HOUR,  # Unsupported
            metrics=[WebTrendsMetric.UNIQUE_USERS],
            properties=[],
        )

        runner = self._create_mock_runner(query)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        # Should reject because HOUR interval is not supported
        assert not builder.can_use_preaggregated_tables()

    def test_get_metric_expr_individual_metrics(self):
        query = WebTrendsQuery(metrics=[], interval=IntervalType.DAY, properties=[])
        runner = self._create_mock_runner(query)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        # Test unique users metric
        unique_users_expr = builder._get_metric_expr(WebTrendsMetric.UNIQUE_USERS)
        assert unique_users_expr.alias == "unique_users"
        assert isinstance(unique_users_expr.expr, ast.Call)

        unique_call = cast(ast.Call, unique_users_expr.expr)
        assert unique_call.name == "uniqMerge"
        assert len(unique_call.args) == 1
        assert isinstance(unique_call.args[0], ast.Field)
        unique_field = cast(ast.Field, unique_call.args[0])
        assert unique_field.chain == ["persons_uniq_state"]

        # Test page views metric
        page_views_expr = builder._get_metric_expr(WebTrendsMetric.PAGE_VIEWS)
        assert page_views_expr.alias == "page_views"
        assert isinstance(page_views_expr.expr, ast.Call)
        page_call = cast(ast.Call, page_views_expr.expr)
        assert page_call.name == "sumMerge"

        # Test sessions metric
        sessions_expr = builder._get_metric_expr(WebTrendsMetric.SESSIONS)
        assert sessions_expr.alias == "sessions"
        assert isinstance(sessions_expr.expr, ast.Call)
        sessions_call = cast(ast.Call, sessions_expr.expr)
        assert sessions_call.name == "uniqMerge"
        assert isinstance(sessions_call.args[0], ast.Field)
        sessions_field = cast(ast.Field, sessions_call.args[0])
        assert sessions_field.chain == ["sessions_uniq_state"]

        # Test bounces metric
        bounces_expr = builder._get_metric_expr(WebTrendsMetric.BOUNCES)
        assert bounces_expr.alias == "bounces"
        assert isinstance(bounces_expr.expr, ast.Call)
        bounces_call = cast(ast.Call, bounces_expr.expr)
        assert bounces_call.name == "sumMerge"
        assert isinstance(bounces_call.args[0], ast.Field)
        bounces_field = cast(ast.Field, bounces_call.args[0])
        assert bounces_field.chain == ["bounces_count_state"]

    def test_get_metric_expr_unknown_metric_raises_error(self):
        query = WebTrendsQuery(metrics=[], interval=IntervalType.DAY, properties=[])
        runner = self._create_mock_runner(query)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        # Test unknown metric raises error
        with pytest.raises(ValueError) as cm:
            builder._get_metric_expr("unknown_metric")  # type: ignore

        assert "Unknown metric" in str(cm.value)

    def test_get_metrics_exprs_defaults_to_unique_users(self):
        query = WebTrendsQuery(metrics=[], interval=IntervalType.DAY, properties=[])
        runner = self._create_mock_runner(query)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        metric_exprs = builder._get_metrics_exprs()

        # Should have one metric (default unique users)
        assert len(metric_exprs) == 1
        assert metric_exprs[0].alias == "unique_users"
        assert isinstance(metric_exprs[0].expr, ast.Call)
        call_expr = cast(ast.Call, metric_exprs[0].expr)
        assert call_expr.name == "uniqMerge"

    def test_get_interval_function_mappings(self):
        query = WebTrendsQuery(metrics=[], interval=IntervalType.DAY, properties=[])
        runner = self._create_mock_runner(query)
        builder = TrendsPreAggregatedQueryBuilder(runner)

        # Test day interval
        runner.query.interval = IntervalType.DAY
        assert builder._get_interval_function() == "toStartOfDay"

        # Test week interval
        runner.query.interval = IntervalType.WEEK
        assert builder._get_interval_function() == "toStartOfWeek"

        # Test month interval
        runner.query.interval = IntervalType.MONTH
        assert builder._get_interval_function() == "toStartOfMonth"
