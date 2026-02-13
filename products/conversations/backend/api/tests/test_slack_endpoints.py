import json
from typing import Any

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache

from rest_framework.test import APIClient
from slack_sdk.errors import SlackApiError

from posthog.models.integration import SlackIntegrationError


class TestSupportSlackEventsAPI(BaseTest):
    client: APIClient

    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"slack_enabled": True, "slack_team_id": "T123"}
        self.team.save()
        self.client = APIClient()
        cache.clear()

    def _post(self, payload: dict[str, Any]):
        return self.client.post(
            "/api/conversations/v1/slack/events",
            data=json.dumps(payload),
            content_type="application/json",
        )

    @patch("products.conversations.backend.api.slack_events.validate_support_request")
    def test_invalid_signature_returns_403(self, mock_validate: MagicMock):
        mock_validate.side_effect = SlackIntegrationError("Invalid")

        response = self._post({"type": "event_callback"})

        assert response.status_code == 403

    @patch("products.conversations.backend.api.slack_events.validate_support_request")
    def test_invalid_json_returns_400(self, mock_validate: MagicMock):
        mock_validate.return_value = None

        response = self.client.post(
            "/api/conversations/v1/slack/events",
            data="{",
            content_type="application/json",
        )

        assert response.status_code == 400

    @patch("products.conversations.backend.api.slack_events.validate_support_request")
    def test_url_verification_returns_challenge(self, mock_validate: MagicMock):
        mock_validate.return_value = None

        response = self._post({"type": "url_verification", "challenge": "challenge123"})

        assert response.status_code == 200
        assert response.json() == {"challenge": "challenge123"}

    @patch("products.conversations.backend.api.slack_events._handle_support_event")
    @patch("products.conversations.backend.api.slack_events.validate_support_request")
    def test_event_id_idempotency_skips_duplicates(self, mock_validate: MagicMock, mock_handle: MagicMock):
        mock_validate.return_value = None
        payload = {
            "type": "event_callback",
            "event_id": "Ev_123",
            "team_id": "T123",
            "event": {"type": "message", "channel": "C1"},
        }

        first = self._post(payload)
        second = self._post(payload)

        assert first.status_code == 202
        assert second.status_code == 200
        assert mock_handle.call_count == 1

    @patch("products.conversations.backend.api.slack_events._handle_support_event")
    @patch("products.conversations.backend.api.slack_events.validate_support_request")
    def test_event_callback_routes_to_handler(self, mock_validate: MagicMock, mock_handle: MagicMock):
        mock_validate.return_value = None

        response = self._post(
            {
                "type": "event_callback",
                "event_id": "Ev_456",
                "team_id": "T123",
                "event": {"type": "reaction_added"},
            }
        )

        assert response.status_code == 202
        mock_handle.assert_called_once()


class TestSlackChannelsAPI(APIBaseTest):
    def test_authentication_required(self):
        response = APIClient().post("/api/conversations/v1/slack/channels", {})
        assert response.status_code == 401

    @patch("products.conversations.backend.api.slack_channels.get_support_slack_bot_token")
    def test_returns_503_when_support_bot_token_missing(self, mock_get_token: MagicMock):
        mock_get_token.return_value = ""

        response = self.client.post("/api/conversations/v1/slack/channels", {})

        assert response.status_code == 503

    @patch("products.conversations.backend.api.slack_channels.WebClient")
    @patch("products.conversations.backend.api.slack_channels.get_support_slack_bot_token")
    def test_handles_slack_api_error(self, mock_get_token: MagicMock, mock_web_client: MagicMock):
        mock_get_token.return_value = "xoxb-support-token"
        client = MagicMock()
        client.conversations_list.side_effect = SlackApiError(message="failed", response={"error": "invalid_auth"})
        mock_web_client.return_value = client

        response = self.client.post("/api/conversations/v1/slack/channels", {})

        assert response.status_code == 400
        assert "Slack API error" in response.json()["error"]

    @patch("products.conversations.backend.api.slack_channels.WebClient")
    @patch("products.conversations.backend.api.slack_channels.get_support_slack_bot_token")
    def test_paginates_and_sorts_channels(self, mock_get_token: MagicMock, mock_web_client: MagicMock):
        mock_get_token.return_value = "xoxb-support-token"
        client = MagicMock()
        client.conversations_list.side_effect = [
            {
                "channels": [{"id": "C2", "name": "beta"}],
                "response_metadata": {"next_cursor": "cursor-2"},
            },
            {
                "channels": [{"id": "C1", "name": "Alpha"}],
                "response_metadata": {"next_cursor": ""},
            },
        ]
        mock_web_client.return_value = client

        response = self.client.post("/api/conversations/v1/slack/channels", {})

        assert response.status_code == 200
        assert response.json()["channels"] == [
            {"id": "C1", "name": "Alpha"},
            {"id": "C2", "name": "beta"},
        ]

    @patch("products.conversations.backend.api.slack_channels.MAX_CHANNEL_PAGES", 2)
    @patch("products.conversations.backend.api.slack_channels.WebClient")
    @patch("products.conversations.backend.api.slack_channels.get_support_slack_bot_token")
    def test_returns_error_when_page_cap_exceeded(self, mock_support_config: MagicMock, mock_web_client: MagicMock):
        mock_support_config.return_value = "xoxb-support-token"
        client = MagicMock()
        client.conversations_list.side_effect = [
            {"channels": [], "response_metadata": {"next_cursor": "cursor-2"}},
            {"channels": [], "response_metadata": {"next_cursor": "cursor-3"}},
        ]
        mock_web_client.return_value = client

        response = self.client.post("/api/conversations/v1/slack/channels", {})

        assert response.status_code == 400
        assert response.json()["error"] == "Too many channel pages returned by Slack"
