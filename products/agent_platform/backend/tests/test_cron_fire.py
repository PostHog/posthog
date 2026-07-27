"""
Integration test: AgentRevision cron_fire action ↔ janitor proxy.

Mocks the janitor HTTP client at the boundary so we don't need a live
janitor process — the action's contract is "call janitor_client.cron_fire
with the right args and pass its response through unchanged." The runtime
side (real PG, real session creation) is exercised in
`services/agent-tests/src/cases/cron-trigger.test.ts`.
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from ..models import AgentApplication, AgentRevision


class TestCronFireAction(APIBaseTest):
    databases = {
        "default",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def setUp(self) -> None:
        super().setUp()
        self.application = AgentApplication.all_teams.create(
            team_id=self.team.id,
            slug="cron-fire-agent",
            name="Cron fire agent",
            description="",
        )
        self.revision = AgentRevision.all_teams.create(
            application=self.application,
            spec={
                "model": "test/x",
                "triggers": [
                    {
                        "type": "cron",
                        "config": {
                            "name": "digest",
                            "schedule": "0 9 * * MON",
                            "prompt": "Run.",
                        },
                    }
                ],
            },
            state="ready",
            bundle_uri="fs://test/",
        )
        self.url = (
            f"/api/projects/{self.team.id}/agent_applications/{self.application.id}"
            f"/revisions/{self.revision.id}/cron/fire/"
        )

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_cron_fire_passes_cron_name_to_janitor_and_returns_response(self, mock_janitor: MagicMock) -> None:
        mock_janitor.return_value.cron_fire.return_value = {
            "ok": True,
            "session_id": "11111111-1111-1111-1111-111111111111",
            "fired_at": "2026-06-01T16:00:00.000Z",
            "idempotency_key": f"cron-manual:{self.revision.id}:digest:click-1",
            "request_id": "click-1",
        }
        res = self.client.post(self.url, {"cron_name": "digest", "request_id": "click-1"}, format="json")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["session_id"], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(res.json()["idempotency_key"], f"cron-manual:{self.revision.id}:digest:click-1")
        mock_janitor.return_value.cron_fire.assert_called_once_with(
            str(self.revision.id), cron_name="digest", request_id="click-1"
        )

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_cron_fire_request_id_is_optional(self, mock_janitor: MagicMock) -> None:
        # Without request_id the janitor mints a UUID; verify we forward None
        # so the janitor falls through to its own generator rather than us
        # silently passing an empty string.
        mock_janitor.return_value.cron_fire.return_value = {
            "ok": True,
            "session_id": "22222222-2222-2222-2222-222222222222",
            "fired_at": "2026-06-01T16:00:00.000Z",
            "idempotency_key": f"cron-manual:{self.revision.id}:digest:generated",
            "request_id": "generated",
        }
        res = self.client.post(self.url, {"cron_name": "digest"}, format="json")
        self.assertEqual(res.status_code, 200)
        mock_janitor.return_value.cron_fire.assert_called_once_with(
            str(self.revision.id), cron_name="digest", request_id=None
        )

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_cron_fire_rejects_missing_cron_name(self, mock_janitor: MagicMock) -> None:
        res = self.client.post(self.url, {}, format="json")
        self.assertEqual(res.status_code, 400)
        mock_janitor.return_value.cron_fire.assert_not_called()

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_cron_fire_rejects_empty_cron_name(self, mock_janitor: MagicMock) -> None:
        res = self.client.post(self.url, {"cron_name": ""}, format="json")
        self.assertEqual(res.status_code, 400)
        mock_janitor.return_value.cron_fire.assert_not_called()
