import hmac
import json
import time
import hashlib
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

from posthog.test.base import APIBaseTest, BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import DatabaseError, OperationalError
from django.http import HttpResponse
from django.utils import timezone

from parameterized import parameterized
from rest_framework.test import APIClient
from slack_sdk.errors import SlackApiError

from posthog.ingress.contracts import DeliveryOwnership, WebhookDelivery
from posthog.ingress.dispatch.dedup import DeliveryDedup
from posthog.models.organization import OrganizationMembership

from products.conversations.backend.facade.api import accept_slack_event, slack_delivery_ownership
from products.conversations.backend.models import (
    ConversationInboundEvent,
    ConversationInboundEventSource,
    TeamConversationsSlackConfig,
)
from products.conversations.backend.models.inbound_event import INBOUND_PAYLOAD_MAX_BYTES

SUPPORT_SLACK_SIGNING_SECRET = "slack-signing-secret"
SLACK_EVENTS_MODULE = "products.conversations.backend.services.slack_events"
WAKE_INBOUND_EVENT = f"{SLACK_EVENTS_MODULE}.wake_inbound_event"


def _signed_headers(body: bytes) -> dict[str, str]:
    timestamp = str(int(time.time()))
    signature = hmac.new(
        SUPPORT_SLACK_SIGNING_SECRET.encode("utf-8"),
        b"v0:" + timestamp.encode("utf-8") + b":" + body,
        hashlib.sha256,
    ).hexdigest()
    return {"x-slack-request-timestamp": timestamp, "x-slack-signature": f"v0={signature}"}


def _forged_headers(signed_body: bytes | None) -> dict[str, str]:
    if signed_body is None:
        return {"x-slack-request-timestamp": "", "x-slack-signature": ""}
    return _signed_headers(signed_body)


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
        signing_secret = patch(
            "products.conversations.backend.support_slack.get_support_slack_settings",
            return_value={"SUPPORT_SLACK_SIGNING_SECRET": SUPPORT_SLACK_SIGNING_SECRET},
        )
        signing_secret.start()
        self.addCleanup(signing_secret.stop)

    def _post_raw(self, body: bytes, **kwargs: Any):
        headers = {**_signed_headers(body), **kwargs.pop("headers", {})}
        return self.client.post(
            "/api/conversations/v1/slack/events",
            data=body,
            content_type="application/json",
            headers=headers,
            **kwargs,
        )

    def _post(self, payload: dict[str, Any], **kwargs: Any):
        return self._post_raw(json.dumps(payload).encode("utf-8"), **kwargs)

    def _post_committed(self, payload: dict[str, Any], **kwargs: Any) -> HttpResponse:
        with self.captureOnCommitCallbacks(execute=True):
            return self._post(payload, **kwargs)

    def _event_row(self) -> ConversationInboundEvent:
        return ConversationInboundEvent.objects.for_team(self.team.id).get()

    @parameterized.expand(
        [
            ("missing_headers", None),
            ("signature_of_another_body", b"another body"),
        ]
    )
    @patch(WAKE_INBOUND_EVENT)
    def test_invalid_signature_returns_403(self, _name: str, signed_body: bytes | None, mock_wake: MagicMock):
        response = self._post({"type": "event_callback", "event_id": "Ev_forged"}, headers=_forged_headers(signed_body))

        assert response.status_code == 403
        mock_wake.assert_not_called()

    @patch(WAKE_INBOUND_EVENT)
    def test_slack_retry_is_recorded_and_processed(self, mock_wake: MagicMock):
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

    def test_invalid_json_returns_400(self):
        response = self._post_raw(b"{")

        assert response.status_code == 400

    def test_url_verification_returns_challenge(self):
        response = self._post({"type": "url_verification", "challenge": "challenge123"})

        assert response.status_code == 200
        assert response.json() == {"challenge": "challenge123"}

    @patch(WAKE_INBOUND_EVENT)
    def test_event_callback_enqueues_processing(self, mock_wake: MagicMock):
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
        # The redelivery reaches the consumer now, and the unique receipt absorbs it into one row.
        assert ConversationInboundEvent.objects.for_team(self.team.id).count() == 1
        assert mock_wake.call_count == 2

    @patch(WAKE_INBOUND_EVENT)
    def test_a_redelivery_reaches_the_handler_past_a_dedup_mark_a_dead_run_left(self, mock_wake: MagicMock):
        # A run that exits between the dedup claim and the receipt commit leaves the mark behind.
        payload = {
            "type": "event_callback",
            "event_id": "Ev_abandoned",
            "team_id": "T123",
            "event": {"type": "message", "channel": "C1"},
        }
        DeliveryDedup().claim(provider="slack", consumer="conversations_slack", delivery_id="Ev_abandoned")

        response = self._post_committed(payload)

        assert response.status_code == 202
        mock_wake.assert_called_once()
        assert self._event_row().source_id == "Ev_abandoned"

    # Spelled out rather than read from the provider, so dropping a type there fails here.
    @parameterized.expand(
        [
            ("app_mention",),
            ("link_shared",),
            ("message",),
            ("reaction_added",),
            ("member_joined_channel",),
            ("member_left_channel",),
        ]
    )
    @patch(WAKE_INBOUND_EVENT)
    def test_every_subscribed_event_type_reaches_the_consumer(self, event_type: str, mock_wake: MagicMock):
        response = self._post_committed(
            {
                "type": "event_callback",
                "event_id": f"Ev_{event_type}",
                "team_id": "T123",
                "event": {"type": event_type},
            }
        )

        assert response.status_code == 202
        mock_wake.assert_called_once()

    @patch(WAKE_INBOUND_EVENT)
    def test_broker_failure_after_commit_still_acknowledges(self, mock_wake: MagicMock):
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

    @patch(WAKE_INBOUND_EVENT)
    @patch(f"{SLACK_EVENTS_MODULE}.accept_inbound_event")
    def test_a_receipt_write_that_raises_is_not_acknowledged(self, mock_accept: MagicMock, mock_wake: MagicMock):
        # The receipt is the product's only durable record of the event, and no sweeper can
        # recover one that was never written, so the request must not earn Slack's 202.
        mock_accept.side_effect = DatabaseError("receipt write failed")
        payload = {
            "type": "event_callback",
            "event_id": "Ev_unwritten",
            "team_id": "T123",
            "event": {"type": "message", "channel": "C1"},
        }

        response = self._post_committed(payload)

        assert response.status_code == 502
        mock_wake.assert_not_called()
        assert not ConversationInboundEvent.objects.unscoped().filter(source_id="Ev_unwritten").exists()

    @patch(WAKE_INBOUND_EVENT)
    def test_oversized_payload_is_tombstoned_and_acknowledged(self, mock_wake: MagicMock):
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

    @parameterized.expand(
        [
            ("the owning region accepts it", 202, 202),
            # Slack redelivers on a non-2xx, so a forward that never landed must not be receipted.
            ("the owning region is unreachable", 500, 502),
        ]
    )
    def test_a_workspace_another_region_owns_is_forwarded_once_from_the_primary(
        self, _name: str, secondary_status: int, expected_status: int
    ):
        payload = {
            "type": "event_callback",
            "event_id": "Ev_forward",
            "team_id": "T_UNKNOWN",
            "event": {"type": "message", "channel": "C1"},
        }

        with (
            patch(WAKE_INBOUND_EVENT) as mock_wake,
            patch("posthog.regions.PRIMARY_REGION_DOMAIN", "testserver"),
            patch("posthog.ingress.dispatch.forward.requests.request") as mock_forward,
        ):
            mock_forward.return_value = MagicMock(ok=200 <= secondary_status < 300, status_code=secondary_status)
            response = self._post(payload)

        assert response.status_code == expected_status
        mock_forward.assert_called_once()
        mock_wake.assert_not_called()
        assert not ConversationInboundEvent.objects.unscoped().filter(source_id="Ev_forward").exists()

    @patch(f"{SLACK_EVENTS_MODULE}.team_for_slack_workspace")
    def test_a_workspace_lookup_that_hits_its_timeout_asks_slack_to_redeliver(self, mock_lookup: MagicMock):
        # The delivery carries the workspace's support messages, so a lookup that never finished
        # must not send them to the other region: it has not shown that region owns the workspace.
        mock_lookup.side_effect = OperationalError("canceling statement due to statement timeout")
        payload = {
            "type": "event_callback",
            "event_id": "Ev_timeout",
            "team_id": "T123",
            "event": {"type": "message", "channel": "C1"},
        }

        with (
            patch(WAKE_INBOUND_EVENT) as mock_wake,
            patch("posthog.regions.PRIMARY_REGION_DOMAIN", "testserver"),
            patch("posthog.ingress.dispatch.forward.requests.request") as mock_forward,
        ):
            refused = self._post(payload)

        assert refused.status_code == 502
        mock_forward.assert_not_called()
        mock_wake.assert_not_called()
        assert not ConversationInboundEvent.objects.unscoped().filter(source_id="Ev_timeout").exists()

        # Nothing claimed a dedup mark, so Slack's redelivery is the recovery rather than a drop.
        mock_lookup.side_effect = None
        mock_lookup.return_value = self.team
        with patch(WAKE_INBOUND_EVENT) as mock_wake:
            redelivered = self._post_committed(payload)

        assert redelivered.status_code == 202
        mock_wake.assert_called_once()
        assert self._event_row().source_id == "Ev_timeout"


class TestSupportSlackDeliveries(BaseTest):
    def setUp(self):
        super().setUp()
        TeamConversationsSlackConfig.objects.update_or_create(
            team=self.team,
            defaults={"slack_team_id": "T123", "slack_bot_token": "xoxb-test"},
        )

    def _delivery(self, context: dict[str, str]) -> WebhookDelivery:
        return WebhookDelivery(
            provider="slack",
            app="supporthog",
            delivery_id="Ev_own",
            event_type="message",
            payload={
                "type": "event_callback",
                "team_id": context.get("slack_team_id", ""),
                "event": {"type": "message"},
            },
            received_at=timezone.now(),
            context=context,
        )

    @parameterized.expand(
        [
            ("a workspace this region holds", {"slack_team_id": "T123"}, DeliveryOwnership.LOCAL),
            ("a workspace it does not", {"slack_team_id": "T_UNKNOWN"}, DeliveryOwnership.ELSEWHERE),
            ("a delivery naming no workspace", {}, DeliveryOwnership.UNDECIDED),
        ]
    )
    def test_ownership(self, _name: str, context: dict[str, str], expected: DeliveryOwnership):
        assert slack_delivery_ownership(self._delivery(context)) == expected

    @parameterized.expand(
        [
            ("the ownership lookup", slack_delivery_ownership),
            ("the consumer", accept_slack_event),
        ]
    )
    @patch(WAKE_INBOUND_EVENT)
    @patch(f"{SLACK_EVENTS_MODULE}.team_for_slack_workspace")
    def test_a_workspace_lookup_that_hits_its_timeout_raises_out_of(
        self, _name: str, entry_point: Callable[[WebhookDelivery], Any], mock_lookup: MagicMock, mock_wake: MagicMock
    ):
        # Answering through a timeout is what ingress cannot recover from: an `ELSEWHERE` guess
        # forwards a workspace this region owns to the other one, and a quiet return receipts a
        # delivery that was never written. Raising asks Slack to redeliver.
        mock_lookup.side_effect = OperationalError("canceling statement due to statement timeout")

        with self.assertRaises(OperationalError):
            entry_point(self._delivery({"slack_team_id": "T123"}))

        mock_wake.assert_not_called()
        assert not ConversationInboundEvent.objects.unscoped().filter(source_id="Ev_own").exists()


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
        signing_secret = patch(
            "products.conversations.backend.support_slack.get_support_slack_settings",
            return_value={"SUPPORT_SLACK_SIGNING_SECRET": SUPPORT_SLACK_SIGNING_SECRET},
        )
        signing_secret.start()
        self.addCleanup(signing_secret.stop)

    def _post_raw(self, payload_field: str, **kwargs):
        # Slack sends interactivity payloads form-encoded, as a `payload` field, and signs the
        # form body rather than the field.
        body = urlencode({"payload": payload_field}).encode("utf-8")
        headers = {**_signed_headers(body), **kwargs.pop("headers", {})}
        return self.client.post(
            "/api/conversations/v1/slack/interactivity",
            data=body,
            content_type="application/x-www-form-urlencoded",
            headers=headers,
            **kwargs,
        )

    def _post(self, payload: Any, **kwargs):
        return self._post_raw(json.dumps(payload), **kwargs)

    def _post_committed(self, payload: Any, **kwargs: Any) -> HttpResponse:
        with self.captureOnCommitCallbacks(execute=True):
            return self._post(payload, **kwargs)

    @parameterized.expand(
        [
            ("missing_headers", None),
            ("signature_of_another_body", b"another body"),
        ]
    )
    def test_invalid_signature_returns_403(self, _name: str, signed_body: bytes | None):
        response = self._post({"type": "block_actions"}, headers=_forged_headers(signed_body))

        assert response.status_code == 403

    def test_invalid_json_returns_400(self):
        response = self._post_raw("{")

        assert response.status_code == 400

    def test_non_object_payload_returns_400(self):
        response = self._post(None)

        assert response.status_code == 400

    @patch(WAKE_INBOUND_EVENT)
    def test_missing_team_id_is_receipted_without_processing(self, mock_wake: MagicMock):
        response = self._post({"type": "block_actions"})

        assert response.status_code == 202
        mock_wake.assert_not_called()

    @patch(WAKE_INBOUND_EVENT)
    def test_block_actions_enqueues_processing(self, mock_wake: MagicMock):
        payload = {
            "type": "block_actions",
            "team": {"id": "T123"},
            "trigger_id": "trig.1",
            "actions": [{"action_id": "open"}],
            "container": {"type": "message", "message_ts": "1.0", "channel_id": "C1"},
        }

        first = self._post_committed(payload)
        second = self._post_committed(payload)

        assert first.status_code == 202
        assert second.status_code == 202
        assert ConversationInboundEvent.objects.for_team(self.team.id).count() == 1
        row = ConversationInboundEvent.objects.for_team(self.team.id).get()
        assert row.source == ConversationInboundEventSource.SLACK_INTERACTIVITY
        assert row.source_id.startswith("trig.1:")
        # Slack sends no delivery id with a click, so ingress dedup has nothing to key on and the
        # consumer runs on both posts. The source id is what keeps the second one to one row.
        assert mock_wake.call_count == 2

    @patch(WAKE_INBOUND_EVENT)
    def test_block_actions_without_trigger_id_hashes_payload_field(self, mock_wake: MagicMock):
        payload = {
            "type": "block_actions",
            "team": {"id": "T123"},
            "actions": [{"action_id": "open"}],
        }
        raw_payload = json.dumps(payload)

        response = self._post_committed(payload)

        assert response.status_code == 202
        row = ConversationInboundEvent.objects.for_team(self.team.id).get()
        assert row.source_id == hashlib.sha256(raw_payload.encode("utf-8")).hexdigest()
        assert row.payload == payload
        mock_wake.assert_called_once()

    @parameterized.expand(
        [
            ("the owning region accepts it", 202, 202),
            # Acking a failed forward with a 2xx silently drops the click. Slack shows the clicker
            # nothing and never resends. A non-2xx surfaces the failure in Slack.
            ("the owning region is unreachable", 500, 502),
        ]
    )
    def test_a_workspace_another_region_owns_is_forwarded_from_the_primary(
        self, _name: str, secondary_status: int, expected_status: int
    ):
        with (
            patch(WAKE_INBOUND_EVENT) as mock_wake,
            patch("posthog.regions.PRIMARY_REGION_DOMAIN", "testserver"),
            patch("posthog.ingress.dispatch.forward.requests.request") as mock_forward,
        ):
            mock_forward.return_value = MagicMock(ok=200 <= secondary_status < 300, status_code=secondary_status)
            response = self._post({"type": "block_actions", "team": {"id": "T_UNKNOWN"}})

        assert response.status_code == expected_status
        mock_forward.assert_called_once()
        mock_wake.assert_not_called()

    @patch("posthog.ingress.dispatch.forward.requests.request")
    @patch(WAKE_INBOUND_EVENT)
    def test_drops_click_when_team_not_found_on_secondary(self, mock_wake: MagicMock, mock_forward: MagicMock):
        response = self._post({"type": "block_actions", "team": {"id": "T_UNKNOWN"}})

        assert response.status_code == 202
        mock_wake.assert_not_called()
        mock_forward.assert_not_called()


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
