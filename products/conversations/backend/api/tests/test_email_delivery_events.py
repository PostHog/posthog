import hmac
import json
import time
import hashlib
from typing import Any
from uuid import uuid4

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from parameterized import parameterized

from posthog.models.comment import Comment

from products.conversations.backend.models import Channel, EmailChannel, EmailDeliveryEvent, EmailOutboxMessage, Status
from products.conversations.backend.models.ticket import Ticket
from products.conversations.backend.services.delivery_status import set_comment_delivery_status

SIGNING_KEY = "test-webhook-signing-key"
ENDPOINT = "/api/conversations/v1/email/events"

PATCH_SIGNING_KEY = patch(
    "products.conversations.backend.mailgun.get_instance_setting",
    return_value=SIGNING_KEY,
)


def _sign(timestamp: str, token: str, key: str = SIGNING_KEY) -> str:
    return hmac.new(key=key.encode(), msg=f"{timestamp}{token}".encode(), digestmod=hashlib.sha256).hexdigest()


def _payload(
    message_id: str,
    event: str = "delivered",
    recipient: str = "customer@example.com",
    event_id: str | None = None,
    key: str = SIGNING_KEY,
    delivery_status: dict[str, Any] | None = None,
    **event_fields: Any,
) -> dict:
    timestamp = str(int(time.time()))
    token = uuid4().hex
    event_data: dict[str, Any] = {
        "event": event,
        "id": event_id or uuid4().hex[:22],
        "timestamp": time.time(),
        "recipient": recipient,
        "message": {"headers": {"message-id": message_id}},
        **event_fields,
    }
    if delivery_status is not None:
        event_data["delivery-status"] = delivery_status
    return {
        "signature": {"timestamp": timestamp, "token": token, "signature": _sign(timestamp, token, key)},
        "event-data": event_data,
    }


class TestEmailDeliveryEventsWebhook(BaseTest):
    def setUp(self):
        super().setUp()
        self.config = EmailChannel.objects.create(
            team=self.team,
            inbound_token="a" * 32,
            from_email="support@example.com",
            from_name="Support",
            domain="example.com",
            domain_verified=True,
        )
        self.ticket = Ticket.objects.create_with_number(
            team=self.team,
            channel_source=Channel.EMAIL,
            email_config=self.config,
            widget_session_id="",
            distinct_id="customer@example.com",
            status=Status.NEW,
            email_from="customer@example.com",
            cc_participants=["cc@example.com"],
            email_subject="Help",
        )
        self.comment = Comment.objects.create(
            team=self.team,
            created_by=self.user,
            scope="conversations_ticket",
            item_id=str(self.ticket.id),
            content="On it!",
            item_context={"author_type": "support", "is_private": False},
        )
        # The reply signal created the outbox row; simulate the state after a
        # successful send, which is when Mailgun starts emitting delivery events.
        self.outbox = EmailOutboxMessage.objects.get(comment=self.comment)
        set_comment_delivery_status(self.team.id, self.comment.id, "sent")

    def _post(self, payload: dict) -> Any:
        return self.client.post(ENDPOINT, data=json.dumps(payload), content_type="application/json")

    def _bare_message_id(self) -> str:
        # Mailgun's event payloads carry message-id without the RFC 5322 angle
        # brackets the outbox stores, so posting the bare form also covers
        # normalization on every test.
        return self.outbox.message_id.strip("<>")

    def _badge(self) -> str | None:
        self.comment.refresh_from_db()
        return (self.comment.item_context or {}).get("email_delivery_status")

    def _rows(self) -> Any:
        return EmailDeliveryEvent.objects.for_team(self.team.id)

    @PATCH_SIGNING_KEY
    def test_rejects_forged_signature(self, _mock_key: MagicMock):
        response = self._post(_payload(self._bare_message_id(), key="attacker-key"))

        assert response.status_code == 403
        assert self._rows().count() == 0
        assert self._badge() == "sent"

    @PATCH_SIGNING_KEY
    def test_rejects_replay_outside_freshness_window(self, _mock_key: MagicMock):
        payload = _payload(self._bare_message_id())
        stale = str(int(time.time()) - 3600)
        payload["signature"] = {"timestamp": stale, "token": "tok", "signature": _sign(stale, "tok")}

        response = self._post(payload)

        assert response.status_code == 403
        assert self._rows().count() == 0

    @parameterized.expand(
        [
            ("delivered_primary", "delivered", None, "customer@example.com", "delivered"),
            ("permanent_fail_primary", "failed", "permanent", "customer@example.com", "failed"),
            ("temporary_fail_primary", "failed", "temporary", "customer@example.com", "sent"),
            ("complained_primary", "complained", None, "customer@example.com", "sent"),
            ("delivered_cc_only", "delivered", None, "cc@example.com", "sent"),
        ]
    )
    @PATCH_SIGNING_KEY
    def test_event_recorded_and_badge_updated(
        self,
        _name: str,
        event: str,
        severity: str | None,
        recipient: str,
        expected_badge: str,
        _mock_key: MagicMock,
    ):
        extra = {"severity": severity} if severity else {}
        response = self._post(_payload(self._bare_message_id(), event=event, recipient=recipient, **extra))

        assert response.status_code == 200
        row = self._rows().get()
        assert row.event == event
        assert row.severity == (severity or "")
        assert row.recipient == recipient
        assert row.message_id == self.outbox.message_id
        assert row.ticket_id == self.ticket.id
        assert row.comment_id == self.comment.id
        assert self._badge() == expected_badge

    @PATCH_SIGNING_KEY
    def test_failure_reason_captured(self, _mock_key: MagicMock):
        response = self._post(
            _payload(
                self._bare_message_id(),
                event="failed",
                severity="permanent",
                reason="bounce",
                delivery_status={"code": 550, "description": "mailbox unavailable"},
            )
        )

        assert response.status_code == 200
        row = self._rows().get()
        assert "bounce" in row.reason
        assert "mailbox unavailable" in row.reason
        assert "code=550" in row.reason

    @PATCH_SIGNING_KEY
    def test_duplicate_event_id_stored_once(self, _mock_key: MagicMock):
        payload = _payload(self._bare_message_id(), event_id="evt-dup-1")

        assert self._post(payload).status_code == 200
        assert self._post(payload).status_code == 200
        assert self._rows().count() == 1

    @PATCH_SIGNING_KEY
    def test_unmatched_message_id_returns_200_without_row(self, _mock_key: MagicMock):
        response = self._post(_payload(f"{uuid4().hex}@unknown.example.com"))

        assert response.status_code == 200
        assert self._rows().count() == 0

    @PATCH_SIGNING_KEY
    def test_untracked_event_type_ignored(self, _mock_key: MagicMock):
        response = self._post(_payload(self._bare_message_id(), event="opened"))

        assert response.status_code == 200
        assert self._rows().count() == 0

    @PATCH_SIGNING_KEY
    def test_malformed_json_returns_400(self, _mock_key: MagicMock):
        response = self.client.post(ENDPOINT, data="not-json", content_type="application/json")

        assert response.status_code == 400
        assert self._rows().count() == 0
