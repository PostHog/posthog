"""
The model-catalog endpoint (`agent_applications/models/`) — a project-agnostic
read that proxies the janitor's `/models` (which owns the gateway-catalog client
and the level map). These guards make sure Django forwards correctly, surfaces
the payload intact, and keeps the action in the read-scope map so personal API
keys can read it.
"""

from __future__ import annotations

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from rest_framework import status

from ..presentation.views import AgentApplicationViewSet


class TestAgentApplicationModels(APIBaseTest):
    databases = {
        "default",
        "agent_platform_db_writer",
        "agent_platform_db_reader",
    }

    def setUp(self) -> None:
        super().setUp()
        self.url = f"/api/projects/{self.team.id}/agent_applications/models/"

    @patch("products.agent_platform.backend.presentation.views._janitor")
    def test_models_proxies_janitor(self, mock_janitor) -> None:
        payload = {
            "models": [
                {
                    "model": "anthropic/claude-haiku-4.5",
                    "provider": "anthropic",
                    "context_window": 200000,
                    "input": 1,
                    "output": 5,
                }
            ],
            "levels": {
                "low": ["anthropic/claude-haiku-4.5", "openai/gpt-5-mini"],
                "medium": ["anthropic/claude-sonnet-4.6", "openai/gpt-5"],
                "high": ["anthropic/claude-opus-4.7", "openai/gpt-5-pro"],
            },
        }
        mock_janitor.return_value.get_models.return_value = payload

        resp = self.client.get(self.url)

        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.json(), payload)
        # No params — the catalog is project-agnostic.
        mock_janitor.return_value.get_models.assert_called_once_with()

    def test_models_is_a_declared_read_action(self) -> None:
        # If `models` slips out of `scope_object_read_actions`, the scope check
        # denies personal-API-key reads — which is exactly what the config UI
        # and the agent builder rely on. Guard against drift.
        self.assertIn("models", AgentApplicationViewSet.scope_object_read_actions)
