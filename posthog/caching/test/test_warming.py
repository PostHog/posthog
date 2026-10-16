from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from typing import Any, Optional

import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import caches

from parameterized import parameterized

from posthog.hogql.errors import QueryError

from posthog.caching.redis_cluster_connection_factory import QUERY_CACHE_ALIAS
from posthog.caching.warming import (
    WARMING_CHAIN_LIFETIME,
    WARMING_START_WINDOW,
    WarmingSelection,
    insights_to_keep_fresh,
    load_warming_settings,
    schedule_warming_for_teams_task,
    warm_insight_cache_task,
)
from posthog.caching.warming_cost import get_warming_durations, record_warming_duration
from posthog.exceptions import ClickHouseAtCapacity, ClickHouseQueryTimeOut
from posthog.models.instance_setting import override_instance_config
from posthog.query_cache.freshness_index import update_target_age
from posthog.scheduling.jitter import deterministic_offset

from products.dashboards.backend.models.dashboard import Dashboard
from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.product_analytics.backend.facade.api import record_insight_views
from products.product_analytics.backend.facade.models import Insight, InsightVariable


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

        record_insight_views(
            team_id=self.team.id,
            user_id=self.user.id,
            last_viewed_at_by_insight_id={
                self.insight2.id: datetime.now(UTC) - timedelta(days=2),
                self.insight4.id: datetime.now(UTC) - timedelta(days=35),
                self.insight5.id: datetime.now(UTC) - timedelta(days=1),
            },
        )

    @patch("posthog.caching.warming.get_stale_insights")
    def test_insights_to_keep_fresh_no_stale_insights(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = []
        insights = insights_to_keep_fresh(self.team, settings=load_warming_settings()).insights
        self.assertEqual(insights, [])

    @patch("posthog.caching.warming.get_stale_insights")
    def test_insights_to_keep_fresh_no_stale_dashboard_insights(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = [
            "2345:",
        ]
        insights = insights_to_keep_fresh(self.team, settings=load_warming_settings()).insights
        exptected_results = [
            (2345, None),
        ]
        self.assertEqual(insights, exptected_results)

    @patch("posthog.caching.warming.get_stale_insights")
    def test_insights_to_keep_fresh_only_insights_with_dashboards(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = [
            "1234:5678",
            "3456:7890",
        ]
        insights = insights_to_keep_fresh(self.team, settings=load_warming_settings()).insights
        expected_results = [
            (3456, 7890),
        ]
        self.assertEqual(insights, expected_results)

    @patch("posthog.caching.warming.get_stale_insights")
    def test_insights_to_keep_fresh_mixed_valid_and_invalid_combos(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = [
            "1234:5678",
            "9999:",
            "3456:7890",
            "8888:7777",
        ]
        insights = insights_to_keep_fresh(self.team, settings=load_warming_settings()).insights
        expected_results = [
            (3456, 7890),
        ]
        self.assertEqual(insights, expected_results)

    @patch("posthog.caching.warming.get_stale_insights")
    def test_insights_to_keep_fresh_insights_not_viewed_recently(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = ["4567:"]
        insights = insights_to_keep_fresh(self.team, settings=load_warming_settings()).insights
        self.assertEqual(insights, [])

    @patch("posthog.caching.warming.get_stale_insights")
    def test_insights_to_keep_fresh_dashboards_not_accessed_recently(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = ["5678:8901"]
        insights = insights_to_keep_fresh(self.team, settings=load_warming_settings()).insights
        self.assertEqual(insights, [])

    @patch("posthog.caching.warming.get_stale_insights")
    def test_insights_to_keep_fresh_combination_of_cases(self, mock_get_stale_insights):
        mock_get_stale_insights.return_value = [
            "1234:5678",
            "2345:",
            "3456:7890",
            "4567:",
        ]
        insights = insights_to_keep_fresh(self.team, settings=load_warming_settings()).insights
        expected_results = [
            (2345, None),
            (3456, 7890),
        ]
        self.assertEqual(insights, expected_results)

    @parameterized.expand(
        [
            ("expensive_insight_viewed_recently", False, 90.0, 2, {}, True, {}),
            ("expensive_insight_not_viewed_recently", False, 90.0, 48, {}, False, {"expensive_not_recently_viewed": 1}),
            ("expensive_tile_accessed_recently", True, 90.0, 2, {}, True, {}),
            ("expensive_tile_not_accessed_recently", True, 90.0, 48, {}, False, {"expensive_not_recently_viewed": 1}),
            ("cheap_insight_not_viewed_recently", False, 30.0, 48, {}, True, {}),
            ("insight_without_a_recorded_warm", False, None, 48, {}, True, {}),
            ("expensive_rule_turned_off", False, 90.0, 48, {"CACHE_WARMING_EXPENSIVE_SECONDS": 0}, True, {}),
            (
                "over_max_duration_even_when_viewed_recently",
                True,
                400.0,
                2,
                {"CACHE_WARMING_MAX_SECONDS": 300},
                False,
                {"over_max_duration": 1},
            ),
            ("under_max_duration_viewed_recently", True, 200.0, 2, {"CACHE_WARMING_MAX_SECONDS": 300}, True, {}),
        ]
    )
    def test_insights_to_keep_fresh_skips_expensive_insights(
        self,
        _name: str,
        on_dashboard: bool,
        last_warm_seconds: Optional[float],
        seen_hours_ago: int,
        instance_settings: dict[str, Any],
        expected_kept: bool,
        expected_skipped: dict[str, int],
    ) -> None:
        caches[QUERY_CACHE_ALIAS].clear()
        seen_at = datetime.now(UTC) - timedelta(hours=seen_hours_ago)
        insight = Insight.objects.create(team=self.team)
        dashboard_id: Optional[int] = None
        if on_dashboard:
            dashboard = Dashboard.objects.create(team=self.team, last_accessed_at=seen_at)
            DashboardTile.objects.create(insight=insight, dashboard=dashboard)
            dashboard_id = dashboard.pk
        else:
            record_insight_views(
                team_id=self.team.id, user_id=self.user.id, last_viewed_at_by_insight_id={insight.id: seen_at}
            )
        if last_warm_seconds is not None:
            record_warming_duration(
                team_id=self.team.pk, insight_id=insight.pk, dashboard_id=dashboard_id, seconds=last_warm_seconds
            )

        with ExitStack() as stack, patch("posthog.caching.warming.get_stale_insights") as mock_get_stale_insights:
            for key, value in instance_settings.items():
                stack.enter_context(override_instance_config(key, value))
            mock_get_stale_insights.return_value = [f"{insight.pk}:{dashboard_id or ''}"]
            selection = insights_to_keep_fresh(self.team, settings=load_warming_settings())

        self.assertEqual(selection.insights, [(insight.pk, dashboard_id)] if expected_kept else [])
        self.assertEqual(selection.skipped, expected_skipped)


class TestScheduleWarmingForTeamsTask(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.organization = self.create_organization_with_features([])
        self.team1 = self.create_team_with_organization(organization=self.organization)
        self.team2 = self.create_team_with_organization(organization=self.organization)

    @patch("posthog.caching.warming.chain")
    @patch("posthog.caching.warming.ph_scoped_capture")
    @patch("posthog.caching.warming.teams_enabled_for_cache_warming", return_value=[])
    @patch("posthog.caching.warming.largest_teams")
    @patch("posthog.caching.warming.insights_to_keep_fresh")
    def test_reports_selected_contexts_separately(
        self, candidates: MagicMock, teams: MagicMock, _enabled: MagicMock, capture: MagicMock, _chain: MagicMock
    ) -> None:
        teams.return_value = [self.team1.pk]
        candidates.return_value = WarmingSelection(
            insights=[(1234, None), (1234, 5678), (2345, 5678)], skipped={"expensive_not_recently_viewed": 4}
        )
        schedule_warming_for_teams_task()
        properties = capture.return_value.__enter__.return_value.call_args.kwargs["properties"]
        assert properties["count"] == 3
        assert properties["standalone_count"] == 1
        assert properties["dashboard_count"] == 2
        assert properties["skipped_expensive_not_recently_viewed"] == 4
        assert properties["skipped_over_max_duration"] == 0

    @patch("posthog.caching.warming.chain")
    @patch("posthog.caching.warming.teams_enabled_for_cache_warming", return_value=[])
    @patch("posthog.caching.warming.largest_teams")
    @patch("posthog.caching.warming.insights_to_keep_fresh")
    def test_excluded_teams_are_not_warmed(
        self, candidates: MagicMock, teams: MagicMock, _enabled: MagicMock, _chain: MagicMock
    ) -> None:
        teams.return_value = [self.team1.pk, self.team2.pk]
        candidates.return_value = WarmingSelection(insights=[], skipped={})

        with override_instance_config("CACHE_WARMING_EXCLUDED_TEAMS", [self.team1.pk]):
            schedule_warming_for_teams_task()

        warmed_team_ids = {call.args[0].pk for call in candidates.call_args_list}
        assert warmed_team_ids == {self.team2.pk}

    @patch("posthog.caching.warming.largest_teams")
    @patch("posthog.caching.warming.insights_to_keep_fresh")
    @patch("posthog.caching.warming.warm_insight_cache_task.si")
    def test_schedule_warming_for_teams_task_with_empty_insight_tuples(
        self, mock_warm_insight_cache_task_si, mock_insights_to_keep_fresh, mock_largest_teams
    ):
        mock_largest_teams.return_value = [self.team1.pk, self.team2.pk]
        mock_insights_to_keep_fresh.return_value = WarmingSelection(insights=[], skipped={})

        schedule_warming_for_teams_task()

        mock_insights_to_keep_fresh.assert_called()
        mock_warm_insight_cache_task_si.assert_not_called()

    def test_schedule_warming_for_teams_task_with_non_empty_insight_tuples(self) -> None:
        dispatched_at = datetime.now(UTC)
        team_by_insight: dict[int, int] = {}
        with time_machine.travel(dispatched_at, tick=False) as clock:
            for team in (self.team1, self.team2):
                team.extra_settings = {"insights_cache_warming": True}
                team.save(update_fields=["extra_settings"])
                dashboard = Dashboard.objects.create(team=team, last_accessed_at=dispatched_at)
                for _ in range(2):
                    insight = Insight.objects.create(team=team)
                    DashboardTile.objects.create(insight=insight, dashboard=dashboard)
                    team_by_insight[insight.pk] = team.pk
                    update_target_age(
                        team_id=team.pk,
                        insight_id=insight.pk,
                        dashboard_id=dashboard.pk,
                        target_age=dispatched_at - timedelta(minutes=1),
                    )

            celery_config = warm_insight_cache_task.app.conf
            self.addCleanup(setattr, celery_config, "task_always_eager", celery_config.task_always_eager)
            celery_config.task_always_eager = False
            with (
                patch("posthog.caching.utils.sync_execute", return_value=[]),
                patch("posthog.caching.warming.posthoganalytics.feature_enabled", return_value=False),
                patch.object(warm_insight_cache_task.app, "send_task") as send_task,
            ):
                send_task.side_effect = lambda *args, **kwargs: clock.shift(timedelta(minutes=2))
                schedule_warming_for_teams_task()

        self.assertEqual(send_task.call_count, 2)
        for call in send_task.call_args_list:
            insight_id, _ = call.args[1]
            expected_start = dispatched_at + deterministic_offset(
                str(team_by_insight[insight_id]), WARMING_START_WINDOW
            )
            self.assertEqual(call.kwargs["eta"], expected_start)
            self.assertEqual(call.kwargs["expires"], expected_start + WARMING_CHAIN_LIFETIME)
            remaining_tasks = call.kwargs["chain"]
            self.assertEqual(len(remaining_tasks), 1)
            self.assertNotIn("eta", remaining_tasks[0].options)
            self.assertEqual(remaining_tasks[0].options["expires"], expected_start + WARMING_CHAIN_LIFETIME)


class TestWarmInsightCacheTask(APIBaseTest):
    def test_warms_the_cache_key_a_dashboard_with_variables_reads(self):
        variable = InsightVariable.objects.create(
            team=self.team, name="Limit", code_name="limit", type="Number", default_value=1
        )
        variable_id = str(variable.id)
        insight = Insight.objects.create(
            team=self.team,
            created_by=self.user,
            query={
                "kind": "DataVisualizationNode",
                "source": {
                    "kind": "HogQLQuery",
                    "query": "select {variables.limit} as n",
                    "variables": {variable_id: {"variableId": variable_id, "code_name": "limit", "value": 1}},
                },
            },
        )
        dashboard = Dashboard.objects.create(
            team=self.team,
            variables={variable_id: {"variableId": variable_id, "code_name": "limit", "value": 5}},
        )
        DashboardTile.objects.create(dashboard=dashboard, insight=insight)

        caches[QUERY_CACHE_ALIAS].clear()
        warm_insight_cache_task(insight.pk, dashboard.pk)
        assert (insight.pk, dashboard.pk) in get_warming_durations(
            team_id=self.team.pk, contexts=[(insight.pk, dashboard.pk)]
        )

        record_warming_duration(team_id=self.team.pk, insight_id=insight.pk, dashboard_id=dashboard.pk, seconds=999.0)
        warm_insight_cache_task(insight.pk, dashboard.pk)
        assert get_warming_durations(team_id=self.team.pk, contexts=[(insight.pk, dashboard.pk)]) == {
            (insight.pk, dashboard.pk): 999.0
        }

        response = self.client.get(
            f"/api/environments/{self.team.pk}/insights/{insight.pk}/?from_dashboard={dashboard.pk}&refresh=force_cache"
        )
        assert response.status_code == 200, response.json()
        assert response.json()["is_cached"] is True
        assert response.json()["result"] == [[5]]

    @patch("posthog.caching.warming.capture_exception")
    @patch("posthog.caching.warming.calculate_for_query_based_insight", side_effect=ClickHouseAtCapacity())
    def test_capacity_errors_propagate_for_retry_instead_of_being_captured(
        self, mock_calculate, mock_capture_exception
    ):
        insight = Insight.objects.create(team=self.team, query={"kind": "TrendsQuery", "series": []})

        with self.assertRaises(ClickHouseAtCapacity):
            warm_insight_cache_task(insight.pk, None)

        mock_capture_exception.assert_not_called()

    @parameterized.expand([("no_previous_record", None, 1.0), ("slower_previous_record", 600.0, 600.0)])
    @patch("posthog.caching.warming.capture_exception")
    @patch("posthog.caching.warming.perf_counter", side_effect=[0.0, 1.0])
    @patch("posthog.caching.warming.calculate_for_query_based_insight", side_effect=ClickHouseQueryTimeOut())
    def test_a_timed_out_warm_keeps_the_slowest_duration(
        self,
        _name: str,
        previous_seconds: Optional[float],
        expected_seconds: float,
        _mock_calculate: MagicMock,
        _mock_perf_counter: MagicMock,
        _mock_capture_exception: MagicMock,
    ) -> None:
        caches[QUERY_CACHE_ALIAS].clear()
        insight = Insight.objects.create(team=self.team, query={"kind": "TrendsQuery", "series": []})
        if previous_seconds is not None:
            record_warming_duration(
                team_id=self.team.pk, insight_id=insight.pk, dashboard_id=None, seconds=previous_seconds
            )

        warm_insight_cache_task(insight.pk, None)

        assert get_warming_durations(team_id=self.team.pk, contexts=[(insight.pk, None)]) == {
            (insight.pk, None): expected_seconds
        }

    @patch("posthog.caching.warming.capture_exception")
    @patch("posthog.caching.warming.ph_scoped_capture")
    @patch("posthog.caching.warming.calculate_for_query_based_insight", side_effect=QueryError("no timestamp binding"))
    def test_query_errors_are_reported_as_an_event_instead_of_being_captured(
        self, mock_calculate, mock_ph_scoped_capture, mock_capture_exception
    ):
        insight = Insight.objects.create(team=self.team, query={"kind": "HogQLQuery", "query": "select 1"})
        capture_ph_event = mock_ph_scoped_capture.return_value.__enter__.return_value

        warm_insight_cache_task(insight.pk, None)

        mock_capture_exception.assert_not_called()
        capture_ph_event.assert_called_once()
        assert capture_ph_event.call_args.kwargs["event"] == "cache warming - insight query error"
        assert capture_ph_event.call_args.kwargs["properties"]["insight_id"] == insight.pk
        assert capture_ph_event.call_args.kwargs["properties"]["error_code"] == "hogql_query_error"
