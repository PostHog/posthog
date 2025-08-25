from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import MagicMock, patch

from posthog.schema import HogQLQueryModifiers, IntervalType, WebTrendsMetric, WebTrendsQuery

from posthog.hogql_queries.web_analytics.web_trends_query_runner import WebTrendsQueryRunner


class TestWebTrendsQueryRunner(ClickhouseTestMixin, APIBaseTest):
    def test_can_instantiate_runner(self):
        query = WebTrendsQuery(
            interval=IntervalType.DAY,
            metrics=[WebTrendsMetric.UNIQUE_USERS],
            properties=[],
        )

        runner = WebTrendsQueryRunner(
            query=query,
            team=self.team,
            modifiers=HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True, convertToProjectTimezone=False),
        )

        self.assertIsNotNone(runner)
        self.assertEqual(runner.query.interval, IntervalType.DAY)
        self.assertEqual(runner.query.metrics, [WebTrendsMetric.UNIQUE_USERS])

    def test_to_query_returns_select_query(self):
        query = WebTrendsQuery(
            interval=IntervalType.DAY,
            metrics=[WebTrendsMetric.UNIQUE_USERS, WebTrendsMetric.PAGE_VIEWS],
            properties=[],
        )

        runner = WebTrendsQueryRunner(
            query=query,
            team=self.team,
            modifiers=HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True, convertToProjectTimezone=False),
        )

        select_query = runner.to_query()
        self.assertIsNotNone(select_query)
        # Verify it's a SelectQuery with expected structure
        self.assertIsNotNone(select_query.select)
        self.assertIsNotNone(select_query.select_from)
        self.assertIsNotNone(select_query.where)
        self.assertIsNotNone(select_query.group_by)
        self.assertIsNotNone(select_query.order_by)

    @patch("posthog.hogql_queries.hogql_query_runner.HogQLQueryRunner")
    def test_calculate_calls_hogql_runner(self, mock_hogql_runner_class):
        # Mock the HogQL runner
        mock_runner_instance = MagicMock()
        mock_response = MagicMock()
        mock_response.results = [["2025-01-01", 100, 500]]
        mock_response.timings = []
        mock_response.types = []
        mock_response.hogql = "SELECT ..."
        mock_runner_instance.calculate.return_value = mock_response
        mock_hogql_runner_class.return_value = mock_runner_instance

        query = WebTrendsQuery(
            interval=IntervalType.DAY,
            metrics=[WebTrendsMetric.UNIQUE_USERS, WebTrendsMetric.PAGE_VIEWS],
            properties=[],
        )

        runner = WebTrendsQueryRunner(
            query=query,
            team=self.team,
            modifiers=HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True, convertToProjectTimezone=False),
        )

        response = runner._calculate()

        # Verify the response structure
        self.assertIsNotNone(response)
        self.assertEqual(len(response.results), 1)
        self.assertEqual(response.results[0].bucket, "2025-01-01")
        self.assertEqual(response.results[0].metrics.UniqueUsers, 100)
        self.assertEqual(response.results[0].metrics.PageViews, 500)
        self.assertTrue(response.usedPreAggregatedTables)

    def test_cannot_use_preaggregated_with_hour_interval(self):
        query = WebTrendsQuery(
            interval=IntervalType.HOUR,  # Not supported
            metrics=[WebTrendsMetric.UNIQUE_USERS],
            properties=[],
        )

        runner = WebTrendsQueryRunner(
            query=query,
            team=self.team,
            modifiers=HogQLQueryModifiers(useWebAnalyticsPreAggregatedTables=True, convertToProjectTimezone=False),
        )

        # Should raise NotImplementedError for non-pre-aggregated fallback
        with self.assertRaises(NotImplementedError):
            runner._calculate()
