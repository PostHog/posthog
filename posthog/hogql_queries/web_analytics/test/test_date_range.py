from datetime import datetime

from posthog.test.base import APIBaseTest, ClickhouseTestMixin
from unittest.mock import Mock, patch

from posthog.hogql_queries.web_analytics.pre_aggregated.date_range import WebAnalyticsPreAggregatedDateRange


class TestWebAnalyticsPreAggregatedDateRange(ClickhouseTestMixin, APIBaseTest):
    def setUp(self):
        super().setUp()

    def test_get_available_date_range_queries_even_without_team_setting(self):
        self.team.web_analytics_pre_aggregated_tables_enabled = False
        self.team.save()

        date_range = WebAnalyticsPreAggregatedDateRange(team=self.team)

        with patch.object(date_range, "_query_and_cache_date_range", return_value=None) as mock_query:
            result = date_range.get_available_date_range()
            mock_query.assert_called_once()
            self.assertIsNone(result)

    @patch("posthog.hogql_queries.web_analytics.pre_aggregated.date_range.execute_hogql_query")
    @patch("posthog.hogql_queries.web_analytics.pre_aggregated.date_range.get_safe_cache")
    @patch("posthog.hogql_queries.web_analytics.pre_aggregated.date_range.cache.set")
    def test_get_available_date_range_queries_and_caches(self, mock_cache_set, mock_get_cache, mock_execute_query):
        mock_get_cache.return_value = None

        min_date = datetime(2023, 11, 1)
        max_date = datetime(2023, 12, 31)

        class MockResponse:
            results = [[min_date, max_date]]

        mock_execute_query.return_value = MockResponse()

        date_range = WebAnalyticsPreAggregatedDateRange(team=self.team)
        result = date_range.get_available_date_range()

        self.assertIsNotNone(result)
        self.assertEqual(result, (min_date, max_date))
        mock_execute_query.assert_called_once()

        # Verify cache was set
        expected_cache_data = {
            "min_date": min_date.isoformat(),
            "max_date": max_date.isoformat(),
        }
        mock_cache_set.assert_called_once()
        call_args = mock_cache_set.call_args
        self.assertEqual(call_args[0][1], expected_cache_data)
        self.assertEqual(call_args[0][2], 1800)  # 30 minutes cache

    @patch("posthog.hogql_queries.web_analytics.pre_aggregated.date_range.get_safe_cache")
    def test_get_available_date_range_uses_cache_when_available(self, mock_get_cache):
        cached_data = {
            "min_date": "2023-11-01T00:00:00",
            "max_date": "2023-12-31T23:59:59",
        }
        mock_get_cache.return_value = cached_data

        date_range = WebAnalyticsPreAggregatedDateRange(team=self.team)
        result = date_range.get_available_date_range()

        expected_result = (
            datetime.fromisoformat("2023-11-01T00:00:00"),
            datetime.fromisoformat("2023-12-31T23:59:59"),
        )
        self.assertEqual(result, expected_result)

    def test_is_date_range_pre_aggregated_returns_false_when_no_data(self):
        date_range = WebAnalyticsPreAggregatedDateRange(team=self.team)

        with patch.object(date_range, "get_available_date_range", return_value=None):
            result = date_range.is_date_range_pre_aggregated(datetime(2023, 11, 15), datetime(2023, 11, 20))

        assert not result

    def test_is_date_range_pre_aggregated_returns_true_when_range_within_available_data(self):
        available_range = (datetime(2023, 11, 1), datetime(2023, 12, 31))
        date_range = WebAnalyticsPreAggregatedDateRange(team=self.team)

        with patch.object(date_range, "get_available_date_range", return_value=available_range):
            result = date_range.is_date_range_pre_aggregated(datetime(2023, 11, 15), datetime(2023, 11, 20))

        self.assertTrue(result)

    def test_is_date_range_pre_aggregated_returns_false_when_range_outside_available_data(self):
        available_range = (datetime(2023, 11, 1), datetime(2023, 12, 31))
        date_range = WebAnalyticsPreAggregatedDateRange(team=self.team)

        with patch.object(date_range, "get_available_date_range", return_value=available_range):
            # Test start date before available range
            result = date_range.is_date_range_pre_aggregated(datetime(2023, 10, 15), datetime(2023, 11, 20))
            assert not result

            # Test end date after available range
            result = date_range.is_date_range_pre_aggregated(datetime(2023, 11, 15), datetime(2024, 1, 20))
            assert not result

            # Test start and end date out of available range
            result = date_range.is_date_range_pre_aggregated(datetime(2023, 10, 15), datetime(2024, 1, 20))
            assert not result

    def test_cache_key_differs_by_team(self):
        from posthog.api.test.test_team import create_team

        team2 = create_team(organization=self.organization)

        date_range1 = WebAnalyticsPreAggregatedDateRange(team=self.team)
        date_range2 = WebAnalyticsPreAggregatedDateRange(team=team2)

        key1 = date_range1._get_cache_key()
        key2 = date_range2._get_cache_key()

        assert key1 != key2

    def test_cache_key_differs_by_v2_tables(self):
        date_range1 = WebAnalyticsPreAggregatedDateRange(team=self.team, use_v2_tables=False)
        date_range2 = WebAnalyticsPreAggregatedDateRange(team=self.team, use_v2_tables=True)

        key1 = date_range1._get_cache_key()
        key2 = date_range2._get_cache_key()

        assert key1 != key2

    @patch("posthog.hogql_queries.web_analytics.pre_aggregated.date_range.execute_hogql_query")
    def test_handles_query_errors_gracefully(self, mock_execute_query):
        mock_execute_query.side_effect = Exception("Database error")

        date_range = WebAnalyticsPreAggregatedDateRange(team=self.team)
        result = date_range.get_available_date_range()

        self.assertIsNone(result)

    @patch("posthog.hogql_queries.web_analytics.pre_aggregated.date_range.execute_hogql_query")
    @patch("posthog.hogql_queries.web_analytics.pre_aggregated.date_range.get_safe_cache")
    def test_handles_empty_query_results(self, mock_get_cache, mock_execute_query):
        mock_get_cache.return_value = None
        mock_execute_query.return_value = Mock(results=[])

        date_range = WebAnalyticsPreAggregatedDateRange(team=self.team)
        result = date_range.get_available_date_range()

        self.assertIsNone(result)
