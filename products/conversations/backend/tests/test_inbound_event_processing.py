from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import SimpleTestCase
from django.utils import timezone

from prometheus_client import REGISTRY

from products.conversations.backend.models import (
    ConversationInboundEvent,
    ConversationInboundEventSource,
    TeamConversationsSlackConfig,
)
from products.conversations.backend.models.inbound_event import INBOUND_PAYLOAD_TTL, INBOUND_TOMBSTONE_TTL
from products.conversations.backend.services.inbound_events import (
    claim_inbound_event,
    complete_inbound_event,
    slack_events_source_id,
    slack_interactivity_source_id,
)
from products.conversations.backend.tasks.slack import process_supporthog_event, sweep_inbound_events


class TestInboundEventSourceId(SimpleTestCase):
    def test_events_prefer_slack_event_id(self) -> None:
        # Two retries of the same Events API callback must collapse to one receipt.
        assert slack_events_source_id(event_id="Ev123", signed_body=b'{"x":1}') == "Ev123"

    def test_events_hash_body_when_event_id_missing(self) -> None:
        # Missing event_id must not collide across different callbacks.
        first = slack_events_source_id(event_id=None, signed_body=b'{"a":1}')
        second = slack_events_source_id(event_id=None, signed_body=b'{"a":2}')
        assert first != second
        assert len(first) == 64

    def test_interactivity_uses_trigger_and_container(self) -> None:
        payload = {
            "trigger_id": "trig.abc",
            "actions": [{"action_id": "open_ticket"}],
            "container": {"type": "message", "message_ts": "1.2", "channel_id": "C1", "thread_ts": "1.1"},
        }
        assert slack_interactivity_source_id(payload=payload, signed_body=b"ignored") == (
            "trig.abc:open_ticket:message:1.2:C1:1.1"
        )

    def test_interactivity_hashes_signed_body_without_trigger_id(self) -> None:
        payload = {"actions": [{"action_id": "open_ticket"}]}
        assert slack_interactivity_source_id(payload=payload, signed_body=b"form-a") != slack_interactivity_source_id(
            payload=payload, signed_body=b"form-b"
        )


class TestInboundEventProcessing(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.conversations_enabled = True
        self.team.conversations_settings = {"slack_enabled": True}
        self.team.save()
        TeamConversationsSlackConfig.objects.update_or_create(
            team=self.team,
            defaults={"slack_team_id": "T123", "slack_bot_token": "xoxb-test"},
        )

    def _create_pending(self, *, source_id: str = "Ev1", **kwargs: object) -> ConversationInboundEvent:
        payload = kwargs.pop("payload", {"type": "event_callback", "event": {"type": "message", "channel": "C1"}})
        return ConversationInboundEvent.objects.for_team(self.team.id).create(
            team=self.team,
            source=ConversationInboundEventSource.SLACK_EVENTS,
            source_id=source_id,
            provider_account_id="T123",
            payload=payload,
            **kwargs,  # type: ignore[arg-type]
        )

    @patch("products.conversations.backend.tasks.slack.handle_support_message")
    def test_provider_retry_after_worker_failure(self, mock_handle: MagicMock) -> None:
        row = self._create_pending()
        mock_handle.side_effect = [RuntimeError("slack timeout"), None]

        with patch(
            "products.conversations.backend.services.inbound_events.retry_delay_seconds",
            return_value=5,
        ):
            process_supporthog_event(inbound_event_id=str(row.id))
        row.refresh_from_db()
        assert row.status == ConversationInboundEvent.Status.PENDING
        assert row.attempts == 1

        row.due_at = timezone.now()
        row.save(update_fields=["due_at", "updated_at"])
        process_supporthog_event(inbound_event_id=str(row.id))
        row.refresh_from_db()
        assert row.status == ConversationInboundEvent.Status.PROCESSED
        assert mock_handle.call_count == 2

    def test_expired_lease_fencing_ignores_stale_complete(self) -> None:
        row = self._create_pending()
        first = claim_inbound_event(str(row.id))
        assert first is not None

        ConversationInboundEvent.objects.unscoped().filter(id=row.id).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1),
            updated_at=timezone.now(),
        )
        second = claim_inbound_event(str(row.id))
        assert second is not None
        assert second.event.fencing_token != first.event.fencing_token
        assert second.expired_reclaim is True

        assert complete_inbound_event(first) is False
        second.event.refresh_from_db()
        assert second.event.status == ConversationInboundEvent.Status.PROCESSING
        assert complete_inbound_event(second) is True
        second.event.refresh_from_db()
        assert second.event.status == ConversationInboundEvent.Status.PROCESSED

    @patch("products.conversations.backend.tasks.slack.handle_support_message")
    def test_duplicate_claim_of_processed_row_is_noop(self, mock_handle: MagicMock) -> None:
        row = self._create_pending()
        process_supporthog_event(inbound_event_id=str(row.id))
        process_supporthog_event(inbound_event_id=str(row.id))
        row.refresh_from_db()
        assert row.status == ConversationInboundEvent.Status.PROCESSED
        mock_handle.assert_called_once()

    @patch("products.conversations.backend.tasks.slack.handle_support_message")
    def test_processing_survives_redis_loss(self, mock_handle: MagicMock) -> None:
        row = self._create_pending()
        with patch.object(cache, "add", side_effect=ConnectionError("redis down")):
            process_supporthog_event(inbound_event_id=str(row.id))
        row.refresh_from_db()
        assert row.status == ConversationInboundEvent.Status.PROCESSED
        mock_handle.assert_called_once()

    @patch("products.conversations.backend.tasks.slack.handle_support_message")
    def test_poison_payload_is_terminal(self, mock_handle: MagicMock) -> None:
        row = self._create_pending(payload=["not", "an", "object"])
        process_supporthog_event(inbound_event_id=str(row.id))
        row.refresh_from_db()
        assert row.status == ConversationInboundEvent.Status.FAILED
        assert row.last_error_code == "poison_payload"
        mock_handle.assert_not_called()

    @patch("products.conversations.backend.tasks.slack.process_supporthog_event")
    def test_sweeper_redrives_due_work_and_cleans_payloads(self, mock_process: MagicMock) -> None:
        due = self._create_pending(source_id="Ev-due")
        future = self._create_pending(source_id="Ev-later")
        ConversationInboundEvent.objects.unscoped().filter(id=future.id).update(
            due_at=timezone.now() + timedelta(hours=1),
            updated_at=timezone.now(),
        )
        terminal = self._create_pending(
            source_id="Ev-old",
            status=ConversationInboundEvent.Status.PROCESSED,
            terminal_at=timezone.now() - INBOUND_PAYLOAD_TTL - timedelta(minutes=1),
            payload={"event": {"type": "message"}},
        )

        with patch("products.conversations.backend.services.inbound_events.ph_scoped_capture") as mock_capture:
            mock_capture.return_value.__enter__.return_value = MagicMock()
            sweep_inbound_events()

        mock_process.delay.assert_called_once_with(inbound_event_id=str(due.id))
        terminal.refresh_from_db()
        assert terminal.payload is None
        future.refresh_from_db()
        assert future.status == ConversationInboundEvent.Status.PENDING

    def test_sweeper_deletes_expired_tombstones(self) -> None:
        row = self._create_pending(
            source_id="Ev-tombstone",
            status=ConversationInboundEvent.Status.FAILED,
            terminal_at=timezone.now() - INBOUND_TOMBSTONE_TTL - timedelta(minutes=1),
            payload=None,
        )
        sweep_inbound_events()
        assert not ConversationInboundEvent.objects.unscoped().filter(id=row.id).exists()

    @patch("products.conversations.backend.tasks.slack.process_supporthog_event")
    def test_sweeper_sets_oldest_ready_age_gauge(self, mock_process: MagicMock) -> None:
        with freeze_time("2026-09-10 12:00:00"):
            self._create_pending(source_id="Ev-old-ready")
            ConversationInboundEvent.objects.unscoped().filter(source_id="Ev-old-ready").update(
                due_at=timezone.now() - timedelta(minutes=3),
                updated_at=timezone.now(),
            )
            sweep_inbound_events()
        age = REGISTRY.get_sample_value("posthog_conversations_inbound_oldest_ready_age_seconds")
        assert age is not None
        assert age >= 180
