from __future__ import annotations

from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

from posthog.models.scoping import team_scope

from products.conversations.backend.models import IncidentStatus, Ticket, TicketAlertRule, TicketIncident
from products.conversations.backend.models.constants import Channel
from products.conversations.backend.temporal.trends import detection
from products.conversations.backend.temporal.trends.scoring import CALM_RUNS_TO_RESOLVE

# UTC-aware: detection buckets by UTC hour and compares against timezone.now().
FROZEN_NOW = datetime(2026, 7, 20, 14, 30, 0, tzinfo=UTC)
# The last complete hour is 13:00–14:00; put ticket bursts here so they're scored.
IN_WINDOW = FROZEN_NOW.replace(hour=13, minute=30, second=0, microsecond=0)


class TestTrendsDetection(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.team.conversations_enabled = True
        self.team.save()
        self._ticket_number = 0
        # Both notification side effects are external boundaries — stub them so tests
        # stay off ClickHouse capture and the notifications facade.
        self.capture_event = patch("products.conversations.backend.events.capture_incident_detected").start()
        self.create_notification = patch("products.notifications.backend.facade.api.create_notification").start()
        self.addCleanup(patch.stopall)

    def _make_tickets(self, count: int, *, when: datetime, channel: str = Channel.WIDGET) -> None:
        for _ in range(count):
            self._ticket_number += 1
            ticket = Ticket.objects.create(
                team=self.team,
                ticket_number=self._ticket_number,
                channel_source=channel,
                widget_session_id=f"session-{self._ticket_number}",
                distinct_id=f"person-{self._ticket_number}",
            )
            # created_at is auto_now_add; override via queryset update to place it in the window.
            Ticket.objects.filter(id=ticket.id).update(created_at=when)

    def _make_rule(self, **kwargs: object) -> TicketAlertRule:
        # TicketAlertRule uses the fail-closed manager; creation needs team context.
        with team_scope(self.team.id):
            return TicketAlertRule.objects.create(team=self.team, **kwargs)

    def test_spike_creates_incident_and_notifies(self) -> None:
        with freeze_time(FROZEN_NOW):
            self._make_tickets(8, when=IN_WINDOW)
            stats = detection.run_detection(self.team.id)

        assert stats.incidents_fired >= 1
        volume_incident = TicketIncident.objects.for_team(self.team.id).get(scope="volume")
        assert volume_incident.status == IncidentStatus.ACTIVE
        assert volume_incident.observed_count >= 8
        assert "title" in volume_incident.details
        self.capture_event.assert_called()
        # No recipients configured, so the whole team is the fallback target.
        notification = self.create_notification.call_args[0][0]
        assert notification.target_type == "team"
        assert notification.target_id == str(self.team.id)

    def test_notification_targets_configured_recipients(self) -> None:
        self.team.conversations_settings = {"notification_recipients": [101, 202]}
        self.team.save()
        with freeze_time(FROZEN_NOW):
            self._make_tickets(8, when=IN_WINDOW)
            detection.run_detection(self.team.id)

        targets = [
            (call.args[0].target_type, call.args[0].target_id) for call in self.create_notification.call_args_list
        ]
        assert targets == [("user", "101"), ("user", "202")]

    def test_active_incident_is_not_duplicated(self) -> None:
        with freeze_time(FROZEN_NOW):
            self._make_tickets(8, when=IN_WINDOW)
            detection.run_detection(self.team.id)
            # Second run, same window, spike still present.
            detection.run_detection(self.team.id)

        active = TicketIncident.objects.for_team(self.team.id).filter(scope="volume", status=IncidentStatus.ACTIVE)
        assert active.count() == 1
        # The event fired only once, on the opening run.
        assert self.capture_event.call_count == 1

    def test_incident_auto_resolves_after_calm_runs(self) -> None:
        # 25 tickets keeps the team on the hourly path (>= 20/week), so the spike leaves
        # the trailing 2h window a few hours later while staying under the 24h age cap —
        # exercising the calm-run counter rather than the aged-out backstop.
        with freeze_time(FROZEN_NOW):
            self._make_tickets(25, when=IN_WINDOW)
            detection.run_detection(self.team.id)

        incident = TicketIncident.objects.for_team(self.team.id).get(scope="volume")
        assert incident.status == IncidentStatus.ACTIVE

        for run in range(1, CALM_RUNS_TO_RESOLVE + 1):
            with freeze_time(FROZEN_NOW + timedelta(hours=3 + run)):
                detection.run_detection(self.team.id)

        incident.refresh_from_db()
        assert incident.status == IncidentStatus.RESOLVED
        assert incident.resolved_at is not None

    def test_dismissed_incident_suppresses_refire(self) -> None:
        with freeze_time(FROZEN_NOW):
            self._make_tickets(8, when=IN_WINDOW)
            detection.run_detection(self.team.id)
            TicketIncident.objects.for_team(self.team.id).filter(scope="volume").update(
                status=IncidentStatus.DISMISSED, updated_at=timezone.now()
            )
            # Spike persists, but the dismissal should hold for the suppression window.
            detection.run_detection(self.team.id)

        assert (
            not TicketIncident.objects.for_team(self.team.id)
            .filter(scope="volume", status=IncidentStatus.ACTIVE)
            .exists()
        )

    def test_overall_volume_suppresses_channel_incident(self) -> None:
        # All tickets share one channel, so overall volume and channel:widget both spike.
        # The hierarchy rule keeps only the overall incident on that run.
        with freeze_time(FROZEN_NOW):
            self._make_tickets(10, when=IN_WINDOW, channel=Channel.WIDGET)
            detection.run_detection(self.team.id)

        active = list(TicketIncident.objects.for_team(self.team.id).filter(status=IncidentStatus.ACTIVE))
        assert len(active) == 1
        assert active[0].scope == "volume"

    def test_absolute_rule_counts_only_matching_tickets(self) -> None:
        rule = self._make_rule(
            name="Email complaints",
            filters={"channel_source": "email"},
            window_minutes=120,
            min_count=5,
            spike_multiplier=None,  # absolute-only
        )
        with freeze_time(FROZEN_NOW):
            self._make_tickets(5, when=IN_WINDOW, channel=Channel.EMAIL)
            self._make_tickets(5, when=IN_WINDOW, channel=Channel.WIDGET)
            detection.run_detection(self.team.id)

        incident = TicketIncident.objects.for_team(self.team.id).get(scope="rule", rule=rule)
        assert incident.status == IncidentStatus.ACTIVE
        assert incident.observed_count == 5  # email only, widget excluded

    def test_absolute_rule_below_threshold_does_not_fire(self) -> None:
        self._make_rule(
            name="Email complaints",
            filters={"channel_source": "email"},
            window_minutes=120,
            min_count=5,
            spike_multiplier=None,
        )
        with freeze_time(FROZEN_NOW):
            self._make_tickets(3, when=IN_WINDOW, channel=Channel.EMAIL)
            detection.run_detection(self.team.id)

        assert not TicketIncident.objects.for_team(self.team.id).filter(scope="rule").exists()
