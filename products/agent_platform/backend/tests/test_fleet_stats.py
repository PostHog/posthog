"""
Focused tests for the fleet-stats endpoints (per-application `stats` action
and the team-wide AgentFleetViewSet). The aggregation itself happens on the
janitor side — these guards make sure Django proxies the right arguments,
surfaces the upstream response intact, and keeps the scope action map in
sync so the new endpoints don't silently regress to "personal API keys can
read team fleet data".
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from ..models import AgentApplication
from ..presentation.views import AgentApplicationViewSet, AgentFleetViewSet


class TestAgentApplicationStats(APIBaseTest):
    databases = {
        "default",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def setUp(self) -> None:
        super().setUp()
        self.application = AgentApplication.all_teams.create(
            team_id=self.team.id,
            slug="stats-agent",
            name="Stats Agent",
            description="",
        )
        self.url = f"/api/projects/{self.team.id}/agent_applications/{self.application.id}/stats/"

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_stats_forwards_to_janitor_with_since(self, mock_janitor) -> None:
        mock_janitor.return_value.aggregate_for_application.return_value = {
            "liveCount": 2,
            "sessionsInWindowCount": 5,
            "spendInWindowUsd": 1.23,
            "lastActivityAt": "2026-05-29T00:00:00Z",
            "failedInWindowCount": 1,
        }
        resp = self.client.get(self.url, {"since": "2026-05-28T00:00:00Z"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json()["liveCount"], 2)
        mock_janitor.return_value.aggregate_for_application.assert_called_once_with(
            str(self.application.id),
            since="2026-05-28T00:00:00Z",
        )

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_stats_omits_since_when_not_supplied(self, mock_janitor) -> None:
        # The janitor side picks the default `since` window (24h) when the
        # query param is absent — Django shouldn't fabricate one and shouldn't
        # forward an empty string either.
        mock_janitor.return_value.aggregate_for_application.return_value = {}
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        mock_janitor.return_value.aggregate_for_application.assert_called_once_with(
            str(self.application.id),
            since=None,
        )

    def test_stats_is_a_declared_read_action(self) -> None:
        # If the action name slips out of `scope_object_read_actions`, the
        # scope check denies personal-API-key reads (correct behavior, but
        # silently breaks any read tooling) — guard against drift.
        self.assertIn("stats", AgentApplicationViewSet.scope_object_read_actions)


class TestAgentFleetViewSet(APIBaseTest):
    databases = {
        "default",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def setUp(self) -> None:
        super().setUp()
        self.url_stats = f"/api/projects/{self.team.id}/agent_fleet/stats/"
        self.url_live = f"/api/projects/{self.team.id}/agent_fleet/live_sessions/"

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_stats_forwards_team_id_and_since(self, mock_janitor) -> None:
        mock_janitor.return_value.aggregate_for_team.return_value = {
            "liveCount": 1,
            "sessionsInWindowCount": 3,
            "spendInWindowUsd": 4.5,
            "lastActivityAt": "2026-05-29T00:00:00Z",
            "failedInWindowCount": 0,
        }
        resp = self.client.get(self.url_stats, {"since": "2026-05-28T00:00:00Z"})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        mock_janitor.return_value.aggregate_for_team.assert_called_once_with(
            self.team.id,
            since="2026-05-28T00:00:00Z",
        )

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_live_sessions_forwards_team_id_and_limit(self, mock_janitor) -> None:
        mock_janitor.return_value.list_live_for_team.return_value = {"results": []}
        resp = self.client.get(self.url_live, {"limit": 25})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        mock_janitor.return_value.list_live_for_team.assert_called_once_with(
            self.team.id,
            limit=25,
        )

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_live_sessions_without_limit_defaults_to_none(self, mock_janitor) -> None:
        # The janitor picks its own 100-default; Django shouldn't impose a
        # different one.
        mock_janitor.return_value.list_live_for_team.return_value = {"results": []}
        resp = self.client.get(self.url_live)
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        mock_janitor.return_value.list_live_for_team.assert_called_once_with(
            self.team.id,
            limit=None,
        )

    def test_live_sessions_rejects_non_integer_limit(self) -> None:
        resp = self.client.get(self.url_live, {"limit": "banana"})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_actions_are_declared_read_actions(self) -> None:
        self.assertIn("stats", AgentFleetViewSet.scope_object_read_actions)
        self.assertIn("live_sessions", AgentFleetViewSet.scope_object_read_actions)
