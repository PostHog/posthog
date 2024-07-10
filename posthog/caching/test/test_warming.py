from posthog.caching.warming import priority_insights
from posthog.models import Insight, DashboardTile, InsightViewed, Dashboard

from datetime import datetime, timedelta, UTC
from unittest.mock import patch

from posthog.test.base import APIBaseTest


class TestWarming(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()

        # Create test insights
        self.insight1 = Insight.objects.create(id=1234, team=self.team)
        self.insight2 = Insight.objects.create(id=2345, team=self.team)
        self.insight3 = Insight.objects.create(id=3456, team=self.team)
        self.insight4 = Insight.objects.create(id=4567, team=self.team)
        self.insight5 = Insight.objects.create(id=5678, team=self.team)

        # Create test dashboards
        self.dashboard1 = Dashboard.objects.create(
            team=self.team, id=5678, last_accessed_at=datetime.now(UTC) - timedelta(days=10)
        )
        self.dashboard2 = Dashboard.objects.create(
            team=self.team, id=7890, last_accessed_at=datetime.now(UTC) - timedelta(days=5)
        )
        self.dashboard3 = Dashboard.objects.create(
            team=self.team, id=8901, last_accessed_at=datetime.now(UTC) - timedelta(days=40)
        )

        # Create test dashboard tiles
        self.dashboard_tile1 = DashboardTile.objects.create(insight=self.insight1, dashboard=self.dashboard1)
        self.dashboard_tile2 = DashboardTile.objects.create(insight=self.insight3, dashboard=self.dashboard2)
        self.dashboard_tile3 = DashboardTile.objects.create(insight=self.insight5, dashboard=self.dashboard3)

        # Create test InsightViewed records
        InsightViewed.objects.create(
            team=self.team, user=self.user, insight=self.insight2, last_viewed_at=datetime.now(UTC) - timedelta(days=2)
        )
        InsightViewed.objects.create(
            team=self.team, user=self.user, insight=self.insight4, last_viewed_at=datetime.now(UTC) - timedelta(days=35)
        )
        InsightViewed.objects.create(
            team=self.team, user=self.user, insight=self.insight5, last_viewed_at=datetime.now(UTC) - timedelta(days=1)
        )

    @patch("posthog.hogql_queries.query_cache.QueryCacheManager.get_stale_insights")
    def test_priority_insights_no_stale_insights(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = []
        insights = list(priority_insights(self.team))
        self.assertEqual(insights, [])

    @patch("posthog.hogql_queries.query_cache.QueryCacheManager.get_stale_insights")
    def test_priority_insights_no_stale_dashboard_insights(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = [
            "2345:",
        ]
        insights = list(priority_insights(self.team))
        exptected_results = [
            (2345, None),
        ]
        self.assertEqual(insights, exptected_results)

    @patch("posthog.hogql_queries.query_cache.QueryCacheManager.get_stale_insights")
    def test_priority_insights_only_insights_with_dashboards(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = [
            "1234:5678",
            "3456:7890",
        ]
        insights = list(priority_insights(self.team))
        expected_results = [
            (3456, 7890),
        ]
        self.assertEqual(insights, expected_results)

    @patch("posthog.hogql_queries.query_cache.QueryCacheManager.get_stale_insights")
    def test_priority_insights_mixed_valid_and_invalid_combos(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = [
            "1234:5678",
            "9999:",
            "3456:7890",
            "8888:7777",
        ]
        insights = list(priority_insights(self.team))
        expected_results = [
            (3456, 7890),
        ]
        self.assertEqual(insights, expected_results)

    @patch("posthog.hogql_queries.query_cache.QueryCacheManager.get_stale_insights")
    def test_priority_insights_insights_not_viewed_recently(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = ["4567:"]
        insights = list(priority_insights(self.team))
        self.assertEqual(insights, [])

    @patch("posthog.hogql_queries.query_cache.QueryCacheManager.get_stale_insights")
    def test_priority_insights_dashboards_not_accessed_recently(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = ["5678:8901"]
        insights = list(priority_insights(self.team))
        self.assertEqual(insights, [])

    @patch("posthog.hogql_queries.query_cache.QueryCacheManager.get_stale_insights")
    def test_priority_insights_combination_of_cases(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = [
            "1234:5678",
            "2345:",
            "3456:7890",
            "4567:",
        ]
        insights = list(priority_insights(self.team))
        expected_results = [
            (2345, None),
            (3456, 7890),
        ]
        self.assertEqual(insights, expected_results)
