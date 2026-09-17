import json
import hashlib
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.http import HttpResponse

from parameterized import parameterized
from rest_framework.test import APIClient
from slack_sdk.errors import SlackApiError

from posthog.models.integration import SlackIntegrationError
from posthog.models.organization import OrganizationMembership

from products.conversations.backend.models import (
    ConversationInboundEvent,
    ConversationInboundEventSource,
    TeamConversationsSlackConfig,
)
from products.conversations.backend.models.inbound_event import INBOUND_PAYLOAD_MAX_BYTES


class TestSupportSlackEventsAPI(BaseTest):
    client: APIClient

    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"slack_enabled": True}
        self.team.save()
        TeamConversationsSlackConfig.objects.update_or_create(
            team=self.team,
            defaults={"slack_team_id": "T123", "slack_bot_token": "xoxb-test"},
        )
        self.client = APIClient()
        cache.clear()

    def _post(self, payload: dict[str, Any], **kwargs):
        return self.client.post(
            "/api/conversations/v1/slack/events",
            data=json.dumps(payload),
            content_type="application/json",
            **kwargs,
        )

    def _post_committed(self, payload: dict[str, Any], **kwargs: Any) -> HttpResponse:
        with self.captureOnCommitCallbacks(execute=True):
            return self._post(payload, **kwargs)

    def _event_row(self) -> ConversationInboundEvent:
        return ConversationInboundEvent.objects.for_team(self.team.id).get()

    @patch("products.conversations.backend.api.slack_events.validate_support_request")
    def test_invalid_signature_returns_403(self, mock_validate: MagicMock):
        mock_validate.side_effect = SlackIntegrationError("Invalid")

        response = self._post({"type": "event_callback"})

        assert response.status_code == 403

    @patch("products.conversations.backend.api.slack_events.wake_inbound_event")
    @patch("products.conversations.backend.api.slack_events.validate_support_request")
    def test_slack_retry_is_recorded_and_processed(self, mock_validate: MagicMock, mock_wake: MagicMock):
        mock_validate.return_value = None
        payload = {
            "type": "event_callback",
            "event_id": "Ev_retry",
            "team_id": "T123",
            "event": {"type": "message", "channel": "C1"},
        }

        response = self._post_committed(
            payload,
            headers={"x-slack-retry-num": "2", "x-slack-retry-reason": "http_timeout"},
        )

        assert response.status_code == 202
        mock_wake.assert_called_once()
        row = self._event_row()
        assert row.provider_retry_num == 2
        assert row.provider_retry_reason == "http_timeout"
        assert row.status == ConversationInboundEvent.Status.PENDING

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

    @patch("products.conversations.backend.api.slack_events.wake_inbound_event")
    @patch("products.conversations.backend.api.slack_events.validate_support_request")
    def test_event_callback_enqueues_processing(self, mock_validate: MagicMock, mock_wake: MagicMock):
        mock_validate.return_value = None
        payload = {
            "type": "event_callback",
            "event_id": "Ev_123",
            "team_id": "T123",
            "event": {"type": "message", "channel": "C1"},
        }

        first = self._post_committed(payload)
        second = self._post_committed(payload)

        assert first.status_code == 202
        assert second.status_code == 202
        assert ConversationInboundEvent.objects.for_team(self.team.id).count() == 1
        assert mock_wake.call_count == 2

    @patch("products.conversations.backend.api.slack_events.wake_inbound_event")
    @patch("products.conversations.backend.api.slack_events.validate_support_request")
    def test_event_callback_routes_to_handler(self, mock_validate: MagicMock, mock_wake: MagicMock):
        mock_validate.return_value = None

        response = self._post_committed(
            {
                "type": "event_callback",
                "event_id": "Ev_456",
                "team_id": "T123",
                "event": {"type": "reaction_added"},
            }
        )

        assert response.status_code == 202
        mock_wake.assert_called_once()

    @patch("products.conversations.backend.api.slack_events.wake_inbound_event")
    @patch("products.conversations.backend.api.slack_events.validate_support_request")
    def test_broker_failure_after_commit_still_acknowledges(self, mock_validate: MagicMock, mock_wake: MagicMock):
        mock_validate.return_value = None
        mock_wake.side_effect = ConnectionError("broker down")
        payload = {
            "type": "event_callback",
            "event_id": "Ev_broker",
            "team_id": "T123",
            "event": {"type": "message", "channel": "C1"},
        }

        response = self._post_committed(payload)

        assert response.status_code == 202
        row = self._event_row()
        assert row.status == ConversationInboundEvent.Status.PENDING
        assert row.source_id == "Ev_broker"

    @patch("products.conversations.backend.api.slack_events.wake_inbound_event")
    @patch("products.conversations.backend.api.slack_events.validate_support_request")
    def test_oversized_payload_is_tombstoned_and_acknowledged(self, mock_validate: MagicMock, mock_wake: MagicMock):
        mock_validate.return_value = None
        payload = {
            "type": "event_callback",
            "event_id": "Ev_poison",
            "team_id": "T123",
            "event": {"type": "message", "text": "x" * (INBOUND_PAYLOAD_MAX_BYTES + 1)},
        }

        response = self._post_committed(payload)

        assert response.status_code == 202
        mock_wake.assert_not_called()
        row = self._event_row()
        assert row.payload is None
        assert row.status == ConversationInboundEvent.Status.FAILED
        assert row.last_error_code == "payload_too_large"

    @patch("products.conversations.backend.api.slack_events.proxy_to_secondary_region")
    @patch("products.conversations.backend.api.slack_events.wake_inbound_event")
    @patch("products.conversations.backend.api.slack_events.validate_support_request")
    def test_proxies_to_secondary_when_team_not_found_on_primary(
        self, mock_validate: MagicMock, mock_wake: MagicMock, mock_proxy: MagicMock
    ):
        mock_validate.return_value = None
        mock_proxy.return_value = True

        with patch("products.conversations.backend.api.slack_events.is_primary_region", return_value=True):
            response = self._post(
                {
                    "type": "event_callback",
                    "event_id": "Ev_proxy",
                    "team_id": "T_UNKNOWN",
                    "event": {"type": "message", "channel": "C1"},
                },
            )

        assert response.status_code == 202
        mock_wake.assert_not_called()
        mock_proxy.assert_called_once()
        assert not ConversationInboundEvent.objects.unscoped().filter(source_id="Ev_proxy").exists()

    @patch("products.conversations.backend.api.slack_events.proxy_to_secondary_region")
    @patch("products.conversations.backend.api.slack_events.wake_inbound_event")
    @patch("products.conversations.backend.api.slack_events.validate_support_request")
    def test_returns_502_when_event_proxy_to_secondary_fails(
        self, mock_validate: MagicMock, mock_wake: MagicMock, mock_proxy: MagicMock
    ):
        mock_validate.return_value = None
        mock_proxy.return_value = False

        with patch("products.conversations.backend.api.slack_events.is_primary_region", return_value=True):
            response = self._post(
                {
                    "type": "event_callback",
                    "event_id": "Ev_proxy_fail",
                    "team_id": "T_UNKNOWN",
                    "event": {"type": "message", "channel": "C1"},
                },
            )

        assert response.status_code == 502
        mock_wake.assert_not_called()

    @patch("products.conversations.backend.api.slack_events.proxy_to_secondary_region")
    @patch("products.conversations.backend.api.slack_events.wake_inbound_event")
    @patch("products.conversations.backend.api.slack_events.validate_support_request")
    def test_drops_event_when_team_not_found_on_secondary(
        self, mock_validate: MagicMock, mock_wake: MagicMock, mock_proxy: MagicMock
    ):
        mock_validate.return_value = None

        with patch("products.conversations.backend.api.slack_events.is_primary_region", return_value=False):
            response = self._post(
                {
                    "type": "event_callback",
                    "event_id": "Ev_drop",
                    "team_id": "T_UNKNOWN",
                    "event": {"type": "message", "channel": "C1"},
                },
            )

        assert response.status_code == 202
        mock_wake.assert_not_called()
        mock_proxy.assert_not_called()


class TestSupportSlackInteractivityAPI(BaseTest):
    client: APIClient

    def setUp(self):
        super().setUp()
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"slack_enabled": True}
        self.team.save()
        TeamConversationsSlackConfig.objects.update_or_create(
            team=self.team,
            defaults={"slack_team_id": "T123", "slack_bot_token": "xoxb-test"},
        )
        self.client = APIClient()
        cache.clear()

    def _post_raw(self, payload_field: str, **kwargs):
        # Slack sends interactivity payloads form-encoded, as a `payload` field.
        return self.client.post(
            "/api/conversations/v1/slack/interactivity",
            data=urlencode({"payload": payload_field}),
            content_type="application/x-www-form-urlencoded",
            **kwargs,
        )

    def _post(self, payload: Any, **kwargs):
        return self._post_raw(json.dumps(payload), **kwargs)

    def _post_committed(self, payload: Any, **kwargs: Any) -> HttpResponse:
        with self.captureOnCommitCallbacks(execute=True):
            return self._post(payload, **kwargs)

    @patch("products.conversations.backend.api.slack_interactivity.validate_support_request")
    def test_invalid_signature_returns_403(self, mock_validate: MagicMock):
        mock_validate.side_effect = SlackIntegrationError("Invalid")

        response = self._post({"type": "block_actions"})

        assert response.status_code == 403

    @patch("products.conversations.backend.api.slack_interactivity.validate_support_request")
    def test_invalid_json_returns_400(self, mock_validate: MagicMock):
        mock_validate.return_value = None

        response = self._post_raw("{")

        assert response.status_code == 400

    @patch("products.conversations.backend.api.slack_interactivity.validate_support_request")
    def test_non_object_payload_returns_400(self, mock_validate: MagicMock):
        mock_validate.return_value = None

        response = self._post(None)

        assert response.status_code == 400

    @patch("products.conversations.backend.api.slack_interactivity.wake_inbound_event")
    @patch("products.conversations.backend.api.slack_interactivity.validate_support_request")
    def test_missing_team_id_returns_200_without_processing(self, mock_validate: MagicMock, mock_wake: MagicMock):
        mock_validate.return_value = None

        response = self._post({"type": "block_actions"})

        assert response.status_code == 200
        mock_wake.assert_not_called()

    @patch("products.conversations.backend.api.slack_interactivity.wake_inbound_event")
    @patch("products.conversations.backend.api.slack_interactivity.validate_support_request")
    def test_block_actions_enqueues_processing(self, mock_validate: MagicMock, mock_wake: MagicMock):
        mock_validate.return_value = None
        payload = {
            "type": "block_actions",
            "team": {"id": "T123"},
            "trigger_id": "trig.1",
            "actions": [{"action_id": "open"}],
            "container": {"type": "message", "message_ts": "1.0", "channel_id": "C1"},
        }

        first = self._post_committed(payload)
        second = self._post_committed(payload)

        assert first.status_code == 200
        assert second.status_code == 200
        assert ConversationInboundEvent.objects.for_team(self.team.id).count() == 1
        row = ConversationInboundEvent.objects.for_team(self.team.id).get()
        assert row.source == ConversationInboundEventSource.SLACK_INTERACTIVITY
        assert row.source_id.startswith("trig.1:")
        assert mock_wake.call_count == 2

    @patch("products.conversations.backend.api.slack_interactivity.wake_inbound_event")
    @patch("products.conversations.backend.api.slack_interactivity.validate_support_request")
    def test_block_actions_without_trigger_id_hashes_payload_field(
        self, mock_validate: MagicMock, mock_wake: MagicMock
    ):
        mock_validate.return_value = None
        payload = {
            "type": "block_actions",
            "team": {"id": "T123"},
            "actions": [{"action_id": "open"}],
        }
        raw_payload = json.dumps(payload)

        response = self._post_committed(payload)

        assert response.status_code == 200
        row = ConversationInboundEvent.objects.for_team(self.team.id).get()
        assert row.source_id == hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()
        mock_wake.assert_called_once()

    @patch("products.conversations.backend.api.slack_interactivity.proxy_to_secondary_region")
    @patch("products.conversations.backend.api.slack_interactivity.wake_inbound_event")
    @patch("products.conversations.backend.api.slack_interactivity.validate_support_request")
    def test_proxies_to_secondary_when_team_not_found_on_primary(
        self, mock_validate: MagicMock, mock_wake: MagicMock, mock_proxy: MagicMock
    ):
        mock_validate.return_value = None
        mock_proxy.return_value = True

        with patch("products.conversations.backend.api.slack_interactivity.is_primary_region", return_value=True):
            response = self._post({"type": "block_actions", "team": {"id": "T_UNKNOWN"}})

        assert response.status_code == 200
        mock_wake.assert_not_called()
        mock_proxy.assert_called_once()

    @patch("products.conversations.backend.api.slack_interactivity.proxy_to_secondary_region")
    @patch("products.conversations.backend.api.slack_interactivity.wake_inbound_event")
    @patch("products.conversations.backend.api.slack_interactivity.validate_support_request")
    def test_returns_502_when_proxy_to_secondary_fails(
        self, mock_validate: MagicMock, mock_wake: MagicMock, mock_proxy: MagicMock
    ):
        # Acking a failed proxy with 200 silently drops the click. Slack shows the
        # clicker nothing and never resends. A non-2xx surfaces the failure in Slack.
        mock_validate.return_value = None
        mock_proxy.return_value = False

        with patch("products.conversations.backend.api.slack_interactivity.is_primary_region", return_value=True):
            response = self._post({"type": "block_actions", "team": {"id": "T_UNKNOWN"}})

        assert response.status_code == 502
        mock_wake.assert_not_called()

    @patch("products.conversations.backend.api.slack_interactivity.proxy_to_secondary_region")
    @patch("products.conversations.backend.api.slack_interactivity.wake_inbound_event")
    @patch("products.conversations.backend.api.slack_interactivity.validate_support_request")
    def test_drops_click_when_team_not_found_on_secondary(
        self, mock_validate: MagicMock, mock_wake: MagicMock, mock_proxy: MagicMock
    ):
        mock_validate.return_value = None

        with patch("products.conversations.backend.api.slack_interactivity.is_primary_region", return_value=False):
            response = self._post({"type": "block_actions", "team": {"id": "T_UNKNOWN"}})

        assert response.status_code == 200
        mock_wake.assert_not_called()
        mock_proxy.assert_not_called()


class TestSlackChannelsAPI(APIBaseTest):
    def test_authentication_required(self):
        response = APIClient().post("/api/conversations/v1/slack/channels", {})
        assert response.status_code == 401

    @patch("products.conversations.backend.support_slack_channels.get_support_slack_bot_token")
    def test_returns_503_when_support_bot_token_missing(self, mock_get_token: MagicMock):
        mock_get_token.return_value = ""

        response = self.client.post("/api/conversations/v1/slack/channels", {})

        assert response.status_code == 503

    @patch("products.conversations.backend.support_slack_channels.WebClient")
    @patch("products.conversations.backend.support_slack_channels.get_support_slack_bot_token")
    def test_handles_slack_api_error(self, mock_get_token: MagicMock, mock_web_client: MagicMock):
        mock_get_token.return_value = "xoxb-support-token"
        client = MagicMock()
        client.conversations_list.side_effect = SlackApiError(message="failed", response={"error": "invalid_auth"})
        mock_web_client.return_value = client

        response = self.client.post("/api/conversations/v1/slack/channels", {})

        assert response.status_code == 400
        assert "Slack API error" in response.json()["error"]

    @patch("products.conversations.backend.support_slack_channels.WebClient")
    @patch("products.conversations.backend.support_slack_channels.get_support_slack_bot_token")
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

    @patch("products.conversations.backend.support_slack_channels.MAX_CHANNEL_PAGES", 2)
    @patch("products.conversations.backend.support_slack_channels.WebClient")
    @patch("products.conversations.backend.support_slack_channels.get_support_slack_bot_token")
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


class TestSlackChannelPermissions(BaseTest):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.user)

    @parameterized.expand(
        [
            ("authorize", "get", "/api/conversations/v1/slack/authorize", {}),
            ("disconnect", "post", "/api/conversations/v1/slack/disconnect", {}),
        ]
    )
    def test_member_cannot_access(self, _name, method, path, body):
        response = getattr(self.client, method)(path, body, content_type="application/json")
        assert response.status_code == 403

    @patch(
        "products.conversations.backend.api.slack_oauth.get_instance_settings",
        return_value={"SUPPORT_SLACK_APP_CLIENT_ID": "test-client-id"},
    )
    def test_admin_can_authorize_slack(self, _mock_settings: MagicMock):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.get("/api/conversations/v1/slack/authorize")
        assert response.status_code == 200

        requested_scopes = parse_qs(urlparse(response.json()["url"]).query)["scope"][0].split(",")
        # Attachment sync in both directions silently degrades without these
        assert "files:read" in requested_scopes
        assert "files:write" in requested_scopes

    @patch(
        "products.conversations.backend.api.slack_oauth.clear_supporthog_slack_token",
    )
    def test_admin_can_disconnect_slack(self, _mock_clear: MagicMock):
        self.organization_membership.level = OrganizationMembership.Level.ADMIN
        self.organization_membership.save()

        response = self.client.post(
            "/api/conversations/v1/slack/disconnect",
            content_type="application/json",
        )
        assert response.status_code == 200
