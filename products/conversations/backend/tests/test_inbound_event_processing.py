from datetime import timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.db import IntegrityError
from django.test import SimpleTestCase
from django.utils import timezone

from prometheus_client import REGISTRY

from posthog.models.team import Team

from products.conversations.backend.models import (
    ConversationInboundEvent,
    ConversationInboundEventSource,
    TeamConversationsSlackConfig,
)
from products.conversations.backend.models.inbound_event import INBOUND_PAYLOAD_TTL, INBOUND_TOMBSTONE_TTL
from products.conversations.backend.services.inbound_events import (
    accept_inbound_event,
    claim_inbound_event,
    complete_inbound_event,
    persist_inbound_event,
    schedule_inbound_retry,
    slack_events_source_id,
    slack_interactivity_source_id,
)
from products.conversations.backend.tasks.slack import process_supporthog_event_receipt, sweep_inbound_events


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
            process_supporthog_event_receipt(inbound_event_id=str(row.id))
        row.refresh_from_db()
        assert row.status == ConversationInboundEvent.Status.PENDING
        assert row.attempts == 1

        row.due_at = timezone.now()
        row.save(update_fields=["due_at", "updated_at"])
        process_supporthog_event_receipt(inbound_event_id=str(row.id))
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

    def test_complete_after_scheduled_retry_is_ignored(self) -> None:
        row = self._create_pending()
        claim = claim_inbound_event(str(row.id))
        assert claim is not None
        assert schedule_inbound_retry(claim, error_code="handler_failed", error="timeout") is not None
        assert complete_inbound_event(claim) is False
        row.refresh_from_db()
        assert row.status == ConversationInboundEvent.Status.PENDING

    def test_persist_check_violation_is_not_treated_as_duplicate(self) -> None:
        with self.assertRaises(IntegrityError):
            persist_inbound_event(
                team=self.team,
                source=ConversationInboundEventSource.SLACK_EVENTS,
                source_id="",
                provider_account_id="T123",
                payload={"type": "event_callback"},
                provider_retry_num=None,
                provider_retry_reason="",
            )

    def test_accept_does_not_wake_before_due(self) -> None:
        self._create_pending()
        ConversationInboundEvent.objects.unscoped().filter(source_id="Ev1").update(
            due_at=timezone.now() + timedelta(minutes=5),
            updated_at=timezone.now(),
        )
        wake = MagicMock()
        with self.captureOnCommitCallbacks(execute=True):
            accept_inbound_event(
                team=self.team,
                source=ConversationInboundEventSource.SLACK_EVENTS,
                source_id="Ev1",
                provider_account_id="T123",
                payload={"type": "event_callback", "event": {"type": "message"}},
                provider_retry_num=2,
                provider_retry_reason="http_timeout",
                wake=wake,
            )
        wake.assert_not_called()

    @patch("products.conversations.backend.tasks.slack.handle_support_message")
    def test_duplicate_claim_of_processed_row_is_noop(self, mock_handle: MagicMock) -> None:
        row = self._create_pending()
        process_supporthog_event_receipt(inbound_event_id=str(row.id))
        process_supporthog_event_receipt(inbound_event_id=str(row.id))
        row.refresh_from_db()
        assert row.status == ConversationInboundEvent.Status.PROCESSED
        mock_handle.assert_called_once()

    @patch("products.conversations.backend.tasks.slack.handle_support_message")
    def test_processing_survives_redis_loss(self, mock_handle: MagicMock) -> None:
        row = self._create_pending()
        with patch.object(cache, "add", side_effect=ConnectionError("redis down")):
            process_supporthog_event_receipt(inbound_event_id=str(row.id))
        row.refresh_from_db()
        assert row.status == ConversationInboundEvent.Status.PROCESSED
        mock_handle.assert_called_once()

    @patch("products.conversations.backend.tasks.slack.handle_support_message")
    def test_receipt_uses_workspace_config_from_child_environment(self, mock_handle: MagicMock) -> None:
        TeamConversationsSlackConfig.objects.filter(team=self.team).update(slack_team_id=None)
        child_team = Team.objects.create(
            organization=self.organization,
            project=self.project,
            parent_team=self.team,
            name="Child environment",
            conversations_settings={"slack_enabled": True},
        )
        TeamConversationsSlackConfig.objects.update_or_create(
            team=child_team,
            defaults={"slack_team_id": "T123", "slack_bot_token": "xoxb-child"},
        )
        row = self._create_pending()

        process_supporthog_event_receipt(inbound_event_id=str(row.id))

        row.refresh_from_db()
        assert row.status == ConversationInboundEvent.Status.PROCESSED
        mock_handle.assert_called_once_with(row.payload["event"], child_team, "T123")

    @patch("products.conversations.backend.tasks.slack.handle_support_message")
    def test_receipt_is_not_processed_after_workspace_moves_to_another_team(self, mock_handle: MagicMock) -> None:
        row = self._create_pending()
        TeamConversationsSlackConfig.objects.filter(team=self.team).update(slack_team_id=None)
        other_team = Team.objects.create_with_data(organization=self.organization, initiating_user=self.user)
        TeamConversationsSlackConfig.objects.update_or_create(
            team=other_team,
            defaults={"slack_team_id": "T123", "slack_bot_token": "xoxb-other"},
        )

        process_supporthog_event_receipt(inbound_event_id=str(row.id))

        row.refresh_from_db()
        assert row.status == ConversationInboundEvent.Status.FAILED
        assert row.last_error_code == "no_team"
        mock_handle.assert_not_called()

    @patch("products.conversations.backend.tasks.slack.handle_support_message")
    def test_poison_payload_is_terminal(self, mock_handle: MagicMock) -> None:
        row = self._create_pending(payload=["not", "an", "object"])
        process_supporthog_event_receipt(inbound_event_id=str(row.id))
        row.refresh_from_db()
        assert row.status == ConversationInboundEvent.Status.FAILED
        assert row.last_error_code == "poison_payload"
        mock_handle.assert_not_called()

    @patch("products.conversations.backend.tasks.slack.process_supporthog_event_receipt")
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

    @patch("products.conversations.backend.tasks.slack.process_supporthog_event_receipt")
    def test_sweeper_measures_expired_lease_age_from_lease_expiry(self, mock_process: MagicMock) -> None:
        with freeze_time("2026-09-10 12:00:00"):
            self._create_pending(source_id="Ev-old-ready")
            ConversationInboundEvent.objects.unscoped().filter(source_id="Ev-old-ready").update(
                status=ConversationInboundEvent.Status.PROCESSING,
                due_at=timezone.now() - timedelta(days=1),
                lease_expires_at=timezone.now() - timedelta(minutes=3),
                updated_at=timezone.now(),
            )
            sweep_inbound_events()
        age = REGISTRY.get_sample_value("posthog_conversations_inbound_oldest_ready_age_seconds")
        assert age == 180
