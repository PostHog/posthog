import uuid
from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from products.conversations.backend.models import Ticket
from products.conversations.backend.models.constants import Status
from products.conversations.backend.tasks import emit_ticket_sla_events

DUE_AT = datetime(2026, 1, 10, 12, 0, 0, tzinfo=UTC)


@patch("products.conversations.backend.events.capture_internal")
class TestEmitTicketSlaEvents(BaseTest):
    def _create_ticket(self, **kwargs) -> Ticket:
        defaults = {
            "team": self.team,
            "widget_session_id": str(uuid.uuid4()),
            "distinct_id": "customer-123",
            "channel_source": "widget",
            "status": Status.OPEN,
            "sla_due_at": DUE_AT,
        }
        defaults.update(kwargs)
        return Ticket.objects.create_with_number(**defaults)

    def _sweep_at(self, at: datetime) -> None:
        with freeze_time(at):
            emit_ticket_sla_events()

    def _emitted(self, mock_capture) -> list[tuple[str, dict]]:
        return [
            (call.kwargs["event_name"], call.kwargs["properties"])
            for call in mock_capture.call_args_list
            if call.kwargs["event_name"].startswith("$conversation_sla")
        ]

    def test_warning_then_breach_lifecycle_with_dedup(self, mock_capture):
        ticket = self._create_ticket(sla_warning_minutes=[60, 30])

        # 50 minutes before due: only the 60-minute threshold has been crossed
        self._sweep_at(DUE_AT - timedelta(minutes=50))
        events = self._emitted(mock_capture)
        assert [name for name, _ in events] == ["$conversation_sla_approaching"]
        assert events[0][1]["threshold_minutes"] == 60
        assert events[0][1]["minutes_remaining"] == 50
        assert events[0][1]["ticket_id"] == str(ticket.id)
        assert events[0][1]["sla_breached"] is False

        # Re-running at the same moment must not re-emit
        self._sweep_at(DUE_AT - timedelta(minutes=50))
        assert len(self._emitted(mock_capture)) == 1

        # 20 minutes before due: the 30-minute threshold fires
        self._sweep_at(DUE_AT - timedelta(minutes=20))
        events = self._emitted(mock_capture)
        assert [name for name, _ in events] == ["$conversation_sla_approaching"] * 2
        assert events[1][1]["threshold_minutes"] == 30

        # Past due: breach fires once
        self._sweep_at(DUE_AT + timedelta(minutes=5))
        self._sweep_at(DUE_AT + timedelta(minutes=6))
        events = self._emitted(mock_capture)
        assert [name for name, _ in events][-1] == "$conversation_sla_breached"
        assert len(events) == 3
        assert events[2][1]["minutes_overdue"] == 5
        assert events[2][1]["sla_breached"] is True

    def test_sla_reset_rearms_warning_and_breach(self, mock_capture):
        ticket = self._create_ticket(sla_warning_minutes=[30])
        self._sweep_at(DUE_AT + timedelta(minutes=1))
        assert [name for name, _ in self._emitted(mock_capture)] == ["$conversation_sla_breached"]

        # A workflow extends the deadline: markers are keyed to the old due_at, so both re-arm
        new_due_at = DUE_AT + timedelta(hours=4)
        Ticket.objects.filter(id=ticket.id).update(sla_due_at=new_due_at)

        self._sweep_at(new_due_at - timedelta(minutes=10))
        self._sweep_at(new_due_at + timedelta(minutes=1))
        assert [name for name, _ in self._emitted(mock_capture)] == [
            "$conversation_sla_breached",
            "$conversation_sla_approaching",
            "$conversation_sla_breached",
        ]

    def test_catchup_after_downtime_emits_only_nearest_threshold(self, mock_capture):
        self._create_ticket(sla_warning_minutes=[120, 60, 30])

        # First sweep runs late: all three thresholds already crossed
        self._sweep_at(DUE_AT - timedelta(minutes=10))
        events = self._emitted(mock_capture)
        assert [name for name, _ in events] == ["$conversation_sla_approaching"]
        assert events[0][1]["threshold_minutes"] == 30

        # The skipped thresholds are marked, not queued for later
        self._sweep_at(DUE_AT - timedelta(minutes=5))
        assert len(self._emitted(mock_capture)) == 1

    def test_team_default_offsets_used_when_ticket_has_none(self, mock_capture):
        self.team.conversations_settings = {"sla_warning_minutes": [15]}
        self.team.save(update_fields=["conversations_settings"])
        self._create_ticket()

        self._sweep_at(DUE_AT - timedelta(minutes=10))
        events = self._emitted(mock_capture)
        assert [name for name, _ in events] == ["$conversation_sla_approaching"]
        assert events[0][1]["threshold_minutes"] == 15

    def test_no_offsets_means_no_warning_but_breach_still_fires(self, mock_capture):
        self._create_ticket()
        self._sweep_at(DUE_AT - timedelta(minutes=10))
        assert self._emitted(mock_capture) == []

        self._sweep_at(DUE_AT + timedelta(minutes=1))
        assert [name for name, _ in self._emitted(mock_capture)] == ["$conversation_sla_breached"]

    def test_resolved_and_no_sla_tickets_are_skipped(self, mock_capture):
        self._create_ticket(status=Status.RESOLVED, sla_warning_minutes=[30])
        self._create_ticket(sla_due_at=None, sla_warning_minutes=[30])

        self._sweep_at(DUE_AT + timedelta(minutes=5))
        assert self._emitted(mock_capture) == []
