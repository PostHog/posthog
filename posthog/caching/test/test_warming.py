from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.caching.warming import (
    _dashboard_warming_priority,
    _iter_stale_insights,
    insights_to_keep_fresh,
    schedule_warming_for_teams_task,
)
from posthog.models.sharing_configuration import SharingConfiguration

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.models.insight import Insight, InsightViewed


class TestWarming(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        current_time = datetime.now(UTC)

        self.insight1 = Insight.objects.create(id=1234, team=self.team)
        self.insight2 = Insight.objects.create(id=2345, team=self.team)
        self.insight3 = Insight.objects.create(id=3456, team=self.team)
        self.insight4 = Insight.objects.create(id=4567, team=self.team)
        self.insight5 = Insight.objects.create(id=5678, team=self.team)

        self.dashboard1 = Dashboard.objects.create(
            team=self.team, id=5678, last_accessed_at=current_time - timedelta(days=10)
        )
        self.dashboard2 = Dashboard.objects.create(
            team=self.team, id=7890, last_accessed_at=current_time - timedelta(days=5)
        )
        self.dashboard3 = Dashboard.objects.create(
            team=self.team, id=8901, last_accessed_at=current_time - timedelta(days=40)
        )

        DashboardTile.objects.create(insight=self.insight1, dashboard=self.dashboard1)
        DashboardTile.objects.create(insight=self.insight3, dashboard=self.dashboard2)
        DashboardTile.objects.create(insight=self.insight5, dashboard=self.dashboard3)

        InsightViewed.objects.create(
            team=self.team, user=self.user, insight=self.insight2, last_viewed_at=current_time - timedelta(days=2)
        )
        InsightViewed.objects.create(
            team=self.team, user=self.user, insight=self.insight4, last_viewed_at=current_time - timedelta(days=35)
        )
        InsightViewed.objects.create(
            team=self.team, user=self.user, insight=self.insight5, last_viewed_at=current_time - timedelta(days=1)
        )

    @parameterized.expand(
        [
            ("human", "embedded"),
            ("embedded", "api"),
        ]
    )
    def test_access_tiers_dominate_recency_and_frequency_without_a_recent_miss(
        self, higher_tier: str, lower_tier: str
    ) -> None:
        current_time = datetime.now(UTC)
        higher_priority, _, _ = _dashboard_warming_priority(
            {higher_tier: {"timestamp": (current_time - timedelta(days=1)).isoformat(), "count": 1}},
            None,
            current_time=current_time,
        )
        lower_priority, _, _ = _dashboard_warming_priority(
            {lower_tier: {"timestamp": current_time.isoformat(), "count": 1000}},
            None,
            current_time=current_time,
        )

        assert higher_priority > lower_priority

    def test_cache_miss_recency_is_scored_independently_from_access_recency(self) -> None:
        current_time = datetime.now(UTC)
        missed_api_priority, _, has_cache_miss_boost = _dashboard_warming_priority(
            {
                "api": {
                    "timestamp": (current_time - timedelta(hours=23)).isoformat(),
                    "count": 1,
                    "last_cache_miss_at": current_time.isoformat(),
                    "cache_miss_count": 1,
                }
            },
            None,
            current_time=current_time,
        )
        human_priority, _, _ = _dashboard_warming_priority(
            {"human": {"timestamp": (current_time - timedelta(days=2)).isoformat(), "count": 1}},
            None,
            current_time=current_time,
        )

        assert has_cache_miss_boost
        assert missed_api_priority > human_priority

    def test_newer_legacy_access_is_used_during_rolling_deploys(self) -> None:
        current_time = datetime.now(UTC)

        priority, access_method, _ = _dashboard_warming_priority(
            {"api": {"timestamp": (current_time - timedelta(days=2)).isoformat(), "count": 1}},
            current_time,
            current_time=current_time,
        )

        assert priority > 0
        assert access_method == "legacy"

    @patch("posthog.caching.warming.STALE_INSIGHT_SCAN_BUDGET", 2)
    @patch("posthog.caching.warming.STALE_INSIGHT_HOT_SCAN_BUDGET", 1)
    @patch("posthog.caching.warming.redis.get_client")
    def test_stale_insight_scan_reserves_hot_and_backlog_budget(self, mock_get_redis_client) -> None:
        current_time = datetime.now(UTC)
        redis_client = mock_get_redis_client.return_value
        redis_client.get.return_value = None
        redis_client.zrevrangebyscore.side_effect = [[b"1:"], [b"2:"]]

        assert list(_iter_stale_insights(team_id=self.team.pk, current_time=current_time)) == ["1:", "2:"]
        assert [call.kwargs["num"] for call in redis_client.zrevrangebyscore.call_args_list] == [1, 1]

    @patch("posthog.caching.warming.STALE_INSIGHT_SCAN_BUDGET", 3)
    @patch("posthog.caching.warming.STALE_INSIGHT_HOT_SCAN_BUDGET", 1)
    @patch("posthog.caching.warming.redis.get_client")
    def test_stale_insight_scan_resumes_after_cursor_member(self, mock_get_redis_client) -> None:
        current_time = datetime.now(UTC)
        redis_client = mock_get_redis_client.return_value
        redis_client.get.return_value = b'{"member": "2:", "score": 20.0}'
        redis_client.zrevrangebyscore.return_value = [b"new:"]
        redis_client.zscore.return_value = 20.0
        redis_client.zrevrank.return_value = 1
        redis_client.zrevrange.return_value = [b"3:", b"4:"]

        assert list(_iter_stale_insights(team_id=self.team.pk, current_time=current_time)) == ["new:", "3:", "4:"]
        redis_client.zrevrange.assert_called_once_with(f"cache_timestamps:{self.team.pk}", 2, 3)

    @patch("posthog.caching.warming._checkpoint_stale_insight_scan")
    @patch("posthog.caching.warming._iter_stale_insights")
    def test_insights_to_keep_fresh_no_stale_insights(self, mock_get_stale_insights, mock_checkpoint):
        mock_get_stale_insights.return_value = []
        insights = list(insights_to_keep_fresh(self.team))
        self.assertEqual(insights, [])
        mock_checkpoint.assert_called_once_with(team_id=self.team.pk, last_identifier=None)

    @patch("posthog.caching.warming._iter_stale_insights")
    def test_insights_to_keep_fresh_no_stale_dashboard_insights(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = [
            "2345:",
        ]
        insights = list(insights_to_keep_fresh(self.team))
        exptected_results = [
            (2345, None),
        ]
        self.assertEqual(insights, exptected_results)

    @patch("posthog.caching.warming._iter_stale_insights")
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

    @patch("posthog.caching.warming._iter_stale_insights")
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

    @patch("posthog.caching.warming._iter_stale_insights")
    def test_insights_to_keep_fresh_insights_not_viewed_recently(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = ["4567:"]
        insights = list(insights_to_keep_fresh(self.team))
        self.assertEqual(insights, [])

    @patch("posthog.caching.warming._iter_stale_insights")
    def test_insights_to_keep_fresh_dashboards_not_accessed_recently(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = ["5678:8901"]
        insights = list(insights_to_keep_fresh(self.team))
        self.assertEqual(insights, [])

    @patch("posthog.caching.warming._iter_stale_insights")
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

    @patch("posthog.caching.warming._iter_stale_insights")
    def test_human_views_are_prioritized_over_frequent_api_reads(self, mock_get_stale_insights):
        current_time = datetime.now(UTC)
        human_dashboard = Dashboard.objects.create(
            team=self.team,
            most_recent_access={"human": {"timestamp": current_time.isoformat(), "count": 1}},
        )
        api_dashboard = Dashboard.objects.create(
            team=self.team,
            most_recent_access={"api": {"timestamp": current_time.isoformat(), "count": 100}},
        )
        human_insight = Insight.objects.create(team=self.team)
        api_insight = Insight.objects.create(team=self.team)
        DashboardTile.objects.create(insight=human_insight, dashboard=human_dashboard)
        DashboardTile.objects.create(insight=api_insight, dashboard=api_dashboard)
        mock_get_stale_insights.return_value = [
            f"{api_insight.id}:{api_dashboard.id}",
            f"{human_insight.id}:{human_dashboard.id}",
        ]

        assert list(insights_to_keep_fresh(self.team)) == [
            (human_insight.id, human_dashboard.id),
            (api_insight.id, api_dashboard.id),
        ]

    @patch("posthog.caching.warming.MAX_WARMING_CANDIDATES_PER_TEAM", 1)
    @patch("posthog.caching.warming._iter_stale_insights")
    def test_recent_cache_miss_can_move_a_candidate_inside_the_warming_budget(self, mock_get_stale_insights):
        current_time = datetime.now(UTC)
        human_dashboard = Dashboard.objects.create(
            team=self.team,
            most_recent_access={"human": {"timestamp": (current_time - timedelta(days=2)).isoformat(), "count": 1}},
        )
        missed_api_dashboard = Dashboard.objects.create(
            team=self.team,
            most_recent_access={
                "api": {
                    "timestamp": current_time.isoformat(),
                    "count": 1,
                    "last_cache_miss_at": current_time.isoformat(),
                    "cache_miss_count": 1,
                }
            },
        )
        human_insight = Insight.objects.create(team=self.team)
        missed_api_insight = Insight.objects.create(team=self.team)
        DashboardTile.objects.create(insight=human_insight, dashboard=human_dashboard)
        DashboardTile.objects.create(insight=missed_api_insight, dashboard=missed_api_dashboard)
        mock_get_stale_insights.return_value = [
            f"{human_insight.id}:{human_dashboard.id}",
            f"{missed_api_insight.id}:{missed_api_dashboard.id}",
        ]

        assert list(insights_to_keep_fresh(self.team)) == [(missed_api_insight.id, missed_api_dashboard.id)]

    @patch("posthog.caching.warming._iter_stale_insights")
    def test_shared_only_dashboard_candidates_use_shared_access_threshold(self, mock_get_stale_insights) -> None:
        current_time = datetime.now(UTC)
        dashboard = Dashboard.objects.create(
            team=self.team,
            most_recent_access={"human": {"timestamp": (current_time - timedelta(days=5)).isoformat(), "count": 1}},
        )
        insight = Insight.objects.create(team=self.team)
        DashboardTile.objects.create(insight=insight, dashboard=dashboard)
        SharingConfiguration.objects.create(team=self.team, dashboard=dashboard, enabled=True)
        mock_get_stale_insights.return_value = [f"{insight.id}:{dashboard.id}"]

        assert list(insights_to_keep_fresh(self.team, shared_only=True)) == []

    @patch("posthog.caching.warming.DASHBOARD_CANDIDATE_QUERY_CHUNK_SIZE", 1)
    @patch("posthog.caching.warming.CACHE_WARMING_CANDIDATE_COUNTER")
    @patch("posthog.caching.warming._iter_stale_insights")
    def test_dashboard_candidates_are_queried_in_chunks_and_metrics_are_aggregated(
        self, mock_get_stale_insights, mock_candidate_counter
    ) -> None:
        current_time = datetime.now(UTC)
        dashboards = [
            Dashboard.objects.create(
                team=self.team,
                most_recent_access={"api": {"timestamp": current_time.isoformat(), "count": 1}},
            )
            for _ in range(2)
        ]
        insights = [Insight.objects.create(team=self.team) for _ in range(2)]
        for insight, dashboard in zip(insights, dashboards):
            DashboardTile.objects.create(insight=insight, dashboard=dashboard)
        mock_get_stale_insights.return_value = [
            f"{insight.id}:{dashboard.id}" for insight, dashboard in zip(insights, dashboards)
        ]

        with patch.object(DashboardTile.objects, "filter", wraps=DashboardTile.objects.filter) as mock_filter:
            assert len(list(insights_to_keep_fresh(self.team))) == 2

        assert mock_filter.call_count == 2
        mock_candidate_counter.labels.assert_called_once_with(
            access_method="api",
            outcome="selected",
            cache_miss_boost="false",
        )
        mock_candidate_counter.labels.return_value.inc.assert_called_once_with(2)


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
