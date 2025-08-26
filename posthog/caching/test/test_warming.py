from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from posthog.caching.warming import insights_to_keep_fresh, schedule_warming_for_teams_task
from posthog.models import Dashboard, DashboardTile, Insight, InsightViewed


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

    @patch("posthog.hogql_queries.query_cache.QueryCacheManagerBase.get_stale_insights")
    def test_insights_to_keep_fresh_no_stale_insights(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = []
        insights = list(insights_to_keep_fresh(self.team))
        self.assertEqual(insights, [])

    @patch("posthog.hogql_queries.query_cache.QueryCacheManagerBase.get_stale_insights")
    def test_insights_to_keep_fresh_no_stale_dashboard_insights(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = [
            "2345:",
        ]
        insights = list(insights_to_keep_fresh(self.team))
        exptected_results = [
            (2345, None),
        ]
        self.assertEqual(insights, exptected_results)

    @patch("posthog.hogql_queries.query_cache.QueryCacheManagerBase.get_stale_insights")
    def test_insights_to_keep_fresh_only_insights_with_dashboards(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = [
            "1234:5678",
            "3456:7890",
        ]
        insights = list(insights_to_keep_fresh(self.team))
        expected_results = [
            (3456, 7890),
        ]
        self.assertEqual(insights, expected_results)

    @patch("posthog.hogql_queries.query_cache.QueryCacheManagerBase.get_stale_insights")
    def test_insights_to_keep_fresh_mixed_valid_and_invalid_combos(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = [
            "1234:5678",
            "9999:",
            "3456:7890",
            "8888:7777",
        ]
        insights = list(insights_to_keep_fresh(self.team))
        expected_results = [
            (3456, 7890),
        ]
        self.assertEqual(insights, expected_results)

    @patch("posthog.hogql_queries.query_cache.QueryCacheManagerBase.get_stale_insights")
    def test_insights_to_keep_fresh_insights_not_viewed_recently(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = ["4567:"]
        insights = list(insights_to_keep_fresh(self.team))
        self.assertEqual(insights, [])

    @patch("posthog.hogql_queries.query_cache.QueryCacheManagerBase.get_stale_insights")
    def test_insights_to_keep_fresh_dashboards_not_accessed_recently(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = ["5678:8901"]
        insights = list(insights_to_keep_fresh(self.team))
        self.assertEqual(insights, [])

    @patch("posthog.hogql_queries.query_cache.QueryCacheManagerBase.get_stale_insights")
    def test_insights_to_keep_fresh_combination_of_cases(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = [
            "1234:5678",
            "2345:",
            "3456:7890",
            "4567:",
        ]
        insights = list(insights_to_keep_fresh(self.team))
        expected_results = [
            (2345, None),
            (3456, 7890),
        ]
        self.assertEqual(insights, expected_results)


class TestScheduleWarmingForTeamsTask(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization = self.create_organization_with_features([])
        self.team1 = self.create_team_with_organization(organization=self.organization)
        self.team2 = self.create_team_with_organization(organization=self.organization)

    @patch("posthog.caching.warming.largest_teams")
    @patch("posthog.caching.warming.insights_to_keep_fresh")
    @patch("posthog.caching.warming.warm_insight_cache_task.si")
    def test_schedule_warming_for_teams_task_with_empty_insight_tuples(
        self, mock_warm_insight_cache_task_si, mock_insights_to_keep_fresh, mock_largest_teams
    ):
        mock_largest_teams.return_value = [self.team1.pk, self.team2.pk]
        mock_insights_to_keep_fresh.return_value = iter([])

        schedule_warming_for_teams_task()

        mock_insights_to_keep_fresh.assert_called()
        mock_warm_insight_cache_task_si.assert_not_called()

    @patch("posthog.caching.warming.largest_teams")
    @patch("posthog.caching.warming.insights_to_keep_fresh")
    @patch("posthog.caching.warming.warm_insight_cache_task.si")
    def test_schedule_warming_for_teams_task_with_non_empty_insight_tuples(
        self, mock_warm_insight_cache_task_si, mock_insights_to_keep_fresh, mock_largest_teams
    ):
        mock_largest_teams.return_value = [self.team1.pk, self.team2.pk]
        mock_insights_to_keep_fresh.return_value = iter([("1234", "5678"), ("2345", None)])

        schedule_warming_for_teams_task()

        mock_insights_to_keep_fresh.assert_called()
        self.assertEqual(mock_warm_insight_cache_task_si.call_count, 2)
        self.assertEqual(mock_warm_insight_cache_task_si.call_args_list[0][0][0], "1234")
        self.assertEqual(mock_warm_insight_cache_task_si.call_args_list[0][0][1], "5678")
        self.assertEqual(mock_warm_insight_cache_task_si.call_args_list[1][0][0], "2345")
