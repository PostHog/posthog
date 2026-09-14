from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any
from uuid import uuid4

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.db import IntegrityError
from django.test import RequestFactory, SimpleTestCase
from django.utils import timezone

from prometheus_client import REGISTRY, CollectorRegistry

from posthog.metrics import pushed_metrics_registry
from posthog.models.team import Team

from products.conversations.backend.models import (
    ConversationInboundEvent,
    ConversationInboundEventSource,
    TeamConversationsSlackConfig,
)
from products.conversations.backend.models.inbound_event import INBOUND_PAYLOAD_TTL, INBOUND_TOMBSTONE_TTL
from products.conversations.backend.services.inbound_events import (
    INBOUND_LEASE_SECONDS,
    INBOUND_MAX_ATTEMPTS,
    INBOUND_SWEEP_BATCH_SIZE,
    INBOUND_SWEEP_MAX_ROUNDS,
    accept_inbound_event,
    claim_inbound_event,
    complete_inbound_event,
    drain_inbound_retention,
    get_current_inbound_claim,
    persist_inbound_event,
    renew_inbound_lease,
    schedule_inbound_retry,
    slack_events_source_id,
    slack_interactivity_source_id,
    slack_retry_metadata,
)
from products.conversations.backend.slack import TICKET_CONFIRM_ACTION_OPEN
from products.conversations.backend.tasks.slack import (
    process_supporthog_event_receipt,
    process_supporthog_interactivity_receipt,
    sweep_inbound_events,
    wake_inbound_event,
)


@contextmanager
def capture_pushed_registries() -> Iterator[list[CollectorRegistry]]:
    captured: list[CollectorRegistry] = []

    @contextmanager
    def wrapper(job_name: str) -> Iterator[CollectorRegistry]:
        with pushed_metrics_registry(job_name) as registry:
            captured.append(registry)
            yield registry

    with patch("products.conversations.backend.services.inbound_events.pushed_metrics_registry", wrapper):
        yield captured


class TestInboundEventSourceId(SimpleTestCase):
    def test_events_prefer_slack_event_id(self) -> None:
        assert slack_events_source_id(event_id="Ev123", signed_body=b'{"x":1}') == "Ev123"

    def test_events_hash_body_when_event_id_missing(self) -> None:
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


class TestSlackRetryMetadata(SimpleTestCase):
    def test_parses_retry_headers(self) -> None:
        request = RequestFactory().post("/", HTTP_X_SLACK_RETRY_NUM="2", HTTP_X_SLACK_RETRY_REASON="http_timeout")
        assert slack_retry_metadata(request) == (2, "http_timeout")

    def test_invalid_retry_num_is_ignored(self) -> None:
        request = RequestFactory().post("/", HTTP_X_SLACK_RETRY_NUM="nope", HTTP_X_SLACK_RETRY_REASON="http_timeout")
        assert slack_retry_metadata(request) == (None, "http_timeout")

    def test_negative_retry_num_is_ignored(self) -> None:
        request = RequestFactory().post("/", HTTP_X_SLACK_RETRY_NUM="-1")
        assert slack_retry_metadata(request) == (None, "")


class TestWakeInboundEvent(SimpleTestCase):
    @patch.object(process_supporthog_event_receipt, "apply_async")
    def test_wake_does_not_retry_broker_publish(self, mock_apply: MagicMock) -> None:
        row = ConversationInboundEvent(id=uuid4(), source=ConversationInboundEventSource.SLACK_EVENTS)
        assert wake_inbound_event(row) is True
        mock_apply.assert_called_once_with(kwargs={"inbound_event_id": str(row.id)}, retry=False)

    @patch.object(process_supporthog_event_receipt, "apply_async", side_effect=ConnectionError("broker down"))
    def test_wake_returns_false_when_broker_publish_fails(self, mock_apply: MagicMock) -> None:
        row = ConversationInboundEvent(id=uuid4(), source=ConversationInboundEventSource.SLACK_EVENTS)
        assert wake_inbound_event(row) is False
        mock_apply.assert_called_once()


class TestDrainInboundRetention(SimpleTestCase):
    def test_stops_on_short_batch(self) -> None:
        calls = {"n": 0}

        def cleanup(_now: object) -> int:
            calls["n"] += 1
            return INBOUND_SWEEP_BATCH_SIZE if calls["n"] == 1 else 3

        assert drain_inbound_retention(cleanup, timezone.now()) == INBOUND_SWEEP_BATCH_SIZE + 3
        assert calls["n"] == 2

    def test_caps_rounds(self) -> None:
        def cleanup(_now: object) -> int:
            return INBOUND_SWEEP_BATCH_SIZE

        assert drain_inbound_retention(cleanup, timezone.now()) == INBOUND_SWEEP_BATCH_SIZE * INBOUND_SWEEP_MAX_ROUNDS


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

    def _create_pending(
        self,
        *,
        source: str = ConversationInboundEventSource.SLACK_EVENTS,
        source_id: str = "Ev1",
        **kwargs: Any,
    ) -> ConversationInboundEvent:
        payload = kwargs.pop("payload", {"type": "event_callback", "event": {"type": "message", "channel": "C1"}})
        return ConversationInboundEvent.objects.for_team(self.team.id).create(
            team=self.team,
            source=source,
            source_id=source_id,
            provider_account_id="T123",
            payload=payload,
            **kwargs,
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

    def test_renew_inbound_lease_extends_expiry(self) -> None:
        with time_machine.travel("2026-09-11 12:00:00", tick=False):
            row = self._create_pending()
            claim = claim_inbound_event(str(row.id))
            assert claim is not None
            fencing_token = claim.event.fencing_token
        with time_machine.travel("2026-09-11 12:10:00", tick=False):
            assert renew_inbound_lease(claim) is True
            claim.event.refresh_from_db()
            assert claim.event.lease_expires_at == timezone.now() + timedelta(seconds=INBOUND_LEASE_SECONDS)
            assert claim.event.fencing_token == fencing_token
            assert claim.event.status == ConversationInboundEvent.Status.PROCESSING

    def test_renew_inbound_lease_rejected_after_reclaim(self) -> None:
        row = self._create_pending()
        first = claim_inbound_event(str(row.id))
        assert first is not None
        ConversationInboundEvent.objects.unscoped().filter(id=row.id).update(
            lease_expires_at=timezone.now() - timedelta(seconds=1),
            updated_at=timezone.now(),
        )
        second = claim_inbound_event(str(row.id))
        assert second is not None
        second_expiry = second.event.lease_expires_at

        assert renew_inbound_lease(first) is False
        second.event.refresh_from_db()
        assert second.event.lease_expires_at == second_expiry
        assert second.event.fencing_token != first.event.fencing_token
        assert complete_inbound_event(first) is False
        assert complete_inbound_event(second) is True

    @patch("products.conversations.backend.tasks.slack._handle_supporthog_event")
    def test_receipt_handler_runs_inside_claim_scope(self, mock_handle: MagicMock) -> None:
        row = self._create_pending()
        seen: list = []

        def capture(*_args: object, **_kwargs: object) -> None:
            seen.append(get_current_inbound_claim())

        mock_handle.side_effect = capture
        process_supporthog_event_receipt(inbound_event_id=str(row.id))
        assert seen[0] is not None
        assert seen[0].event.id == row.id

    def test_complete_after_scheduled_retry_is_ignored(self) -> None:
        row = self._create_pending()
        claim = claim_inbound_event(str(row.id))
        assert claim is not None
        assert schedule_inbound_retry(claim, error_code="handler_failed", error="timeout") is not None
        assert complete_inbound_event(claim) is False
        row.refresh_from_db()
        assert row.status == ConversationInboundEvent.Status.PENDING

    def test_expired_receipt_is_failed_after_max_attempts(self) -> None:
        row = self._create_pending(
            status=ConversationInboundEvent.Status.PROCESSING,
            attempts=INBOUND_MAX_ATTEMPTS,
            lease_expires_at=timezone.now() - timedelta(seconds=1),
        )

        assert claim_inbound_event(str(row.id)) is None

        row.refresh_from_db()
        assert row.status == ConversationInboundEvent.Status.FAILED
        assert row.last_error_code == "max_attempts"
        assert row.terminal_at is not None

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

    @patch("products.conversations.backend.tasks.slack.cache.add")
    @patch("products.conversations.backend.tasks.slack.handle_support_message")
    def test_receipt_does_not_use_redis_dedupe(self, mock_handle: MagicMock, mock_cache_add: MagicMock) -> None:
        row = self._create_pending()
        process_supporthog_event_receipt(inbound_event_id=str(row.id))
        mock_cache_add.assert_not_called()
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
        mock_handle.assert_called_once_with(
            {"type": "message", "channel": "C1"},
            child_team,
            "T123",
        )

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
        assert row.status == ConversationInboundEvent.Status.PENDING
        assert row.last_error_code == "no_team"
        mock_handle.assert_not_called()

    @patch("products.conversations.backend.tasks.slack._update_supporthog_prompt", return_value="updated")
    @patch("products.conversations.backend.tasks.slack.create_ticket_from_confirmation", return_value=None)
    def test_exhausted_interactivity_is_failed(self, mock_create: MagicMock, mock_update: MagicMock) -> None:
        row = self._create_pending(
            source=ConversationInboundEventSource.SLACK_INTERACTIVITY,
            attempts=INBOUND_MAX_ATTEMPTS - 1,
            payload={
                "type": "block_actions",
                "team": {"id": "T123"},
                "container": {"channel_id": "C1", "message_ts": "1.0"},
                "actions": [
                    {
                        "action_id": TICKET_CONFIRM_ACTION_OPEN,
                        "value": '{"channel": "C1", "message_ts": "1.0"}',
                    }
                ],
            },
        )

        process_supporthog_interactivity_receipt(inbound_event_id=str(row.id))

        row.refresh_from_db()
        assert row.status == ConversationInboundEvent.Status.FAILED
        assert row.last_error_code == "interactivity_failed"
        mock_create.assert_called_once()
        mock_update.assert_called_once()

    @patch("products.conversations.backend.tasks.slack.handle_support_message")
    def test_poison_payload_is_terminal(self, mock_handle: MagicMock) -> None:
        row = self._create_pending(payload=["not", "an", "object"])
        process_supporthog_event_receipt(inbound_event_id=str(row.id))
        row.refresh_from_db()
        assert row.status == ConversationInboundEvent.Status.FAILED
        assert row.last_error_code == "poison_payload"
        mock_handle.assert_not_called()

    @patch("products.conversations.backend.tasks.slack.wake_inbound_event")
    def test_sweeper_redrives_due_work_and_cleans_payloads(self, mock_wake: MagicMock) -> None:
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

        sweep_inbound_events()

        mock_wake.assert_called_once()
        assert str(mock_wake.call_args.args[0].id) == str(due.id)
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

    def test_sweeper_drains_more_than_one_tombstone_batch(self) -> None:
        cutoff = timezone.now() - INBOUND_TOMBSTONE_TTL - timedelta(minutes=1)
        ConversationInboundEvent.objects.for_team(self.team.id).bulk_create(
            [
                ConversationInboundEvent(
                    team=self.team,
                    source=ConversationInboundEventSource.SLACK_EVENTS,
                    source_id=f"Ev-tombstone-{i}",
                    provider_account_id="T123",
                    status=ConversationInboundEvent.Status.FAILED,
                    terminal_at=cutoff,
                    payload=None,
                )
                for i in range(INBOUND_SWEEP_BATCH_SIZE + 1)
            ]
        )

        sweep_inbound_events()

        assert ConversationInboundEvent.objects.unscoped().filter(source_id__startswith="Ev-tombstone-").count() == 0

    @patch("products.conversations.backend.tasks.slack.wake_inbound_event")
    def test_sweeper_measures_expired_lease_age_from_lease_expiry(self, mock_wake: MagicMock) -> None:
        with time_machine.travel("2026-09-10 12:00:00", tick=False):
            self._create_pending(source_id="Ev-old-ready")
            ConversationInboundEvent.objects.unscoped().filter(source_id="Ev-old-ready").update(
                status=ConversationInboundEvent.Status.PROCESSING,
                due_at=timezone.now() - timedelta(days=1),
                lease_expires_at=timezone.now() - timedelta(minutes=3),
                updated_at=timezone.now(),
            )
            with capture_pushed_registries() as registries:
                sweep_inbound_events()
        age = registries[0].get_sample_value("posthog_conversations_inbound_oldest_ready_age_seconds")
        assert age == 180
        last_sweep = registries[0].get_sample_value("posthog_conversations_inbound_last_sweep_timestamp_seconds")
        assert last_sweep is not None
        assert REGISTRY.get_sample_value("posthog_conversations_inbound_oldest_ready_age_seconds") is None
