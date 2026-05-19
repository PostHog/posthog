"""Tests for the investigation-agent trigger helpers in posthog/temporal/alerts/investigation.py.

The decision logic — should we kick off an investigation, can we claim the cooldown
slot — runs synchronously inside the `evaluate_alert` activity. These tests exercise
the helpers directly so they're independent of Temporal harnessing.
"""

from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import AlertState

from posthog.models import Insight
from posthog.models.alert import AlertCheck, AlertConfiguration, InvestigationStatus
from posthog.temporal.alerts.investigation import claim_investigation_slot, should_trigger_investigation


class TestShouldTriggerInvestigation(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="test insight")
        self.alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=self.insight,
            name="anomaly alert",
            detector_config={"type": "zscore", "threshold": 0.95, "window": 30},
            investigation_agent_enabled=True,
        )

    def test_triggers_on_transition_to_firing(self) -> None:
        assert should_trigger_investigation(
            self.alert,
            previous_state=AlertState.NOT_FIRING,
            new_state=AlertState.FIRING,
        )

    @parameterized.expand(
        [
            ("already_firing", AlertState.FIRING, AlertState.FIRING),
            ("still_not_firing", AlertState.NOT_FIRING, AlertState.NOT_FIRING),
            ("transition_to_errored", AlertState.NOT_FIRING, AlertState.ERRORED),
        ]
    )
    def test_does_not_trigger_on_other_transitions(self, _name: str, previous: str, new: str) -> None:
        assert not should_trigger_investigation(self.alert, previous_state=previous, new_state=new)

    def test_does_not_trigger_when_not_opted_in(self) -> None:
        self.alert.investigation_agent_enabled = False
        self.alert.save()
        assert not should_trigger_investigation(
            self.alert,
            previous_state=AlertState.NOT_FIRING,
            new_state=AlertState.FIRING,
        )

    def test_does_not_trigger_for_threshold_only_alerts(self) -> None:
        self.alert.detector_config = None
        self.alert.save()
        assert not should_trigger_investigation(
            self.alert,
            previous_state=AlertState.NOT_FIRING,
            new_state=AlertState.FIRING,
        )


class TestClaimInvestigationSlot(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="test insight")
        self.alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=self.insight,
            name="anomaly alert",
            detector_config={"type": "zscore", "threshold": 0.95, "window": 30},
            investigation_agent_enabled=True,
        )

    def _make_check(self, *, investigation_status: str | None = None) -> AlertCheck:
        return AlertCheck.objects.create(
            alert_configuration=self.alert,
            state=AlertState.FIRING,
            calculated_value=42.0,
            investigation_status=investigation_status,
        )

    def test_claims_when_no_recent_investigation(self) -> None:
        check = self._make_check()
        assert claim_investigation_slot(self.alert, check)
        check.refresh_from_db()
        assert check.investigation_status == InvestigationStatus.PENDING

    def test_skips_when_recent_investigation_exists(self) -> None:
        now = datetime(2026, 4, 30, 10, 0, tzinfo=UTC)
        with freeze_time(now - timedelta(minutes=10)):
            self._make_check(investigation_status=InvestigationStatus.DONE)

        with freeze_time(now):
            new_check = self._make_check()
            assert not claim_investigation_slot(self.alert, new_check)

        new_check.refresh_from_db()
        assert new_check.investigation_status == InvestigationStatus.SKIPPED

    def test_claims_after_cooldown_expires(self) -> None:
        now = datetime(2026, 4, 30, 10, 0, tzinfo=UTC)
        with freeze_time(now - timedelta(hours=2)):
            self._make_check(investigation_status=InvestigationStatus.DONE)

        with freeze_time(now):
            new_check = self._make_check()
            assert claim_investigation_slot(self.alert, new_check)

        new_check.refresh_from_db()
        assert new_check.investigation_status == InvestigationStatus.PENDING

    @parameterized.expand(
        [
            ("running", InvestigationStatus.RUNNING),
            ("done", InvestigationStatus.DONE),
            ("pending", InvestigationStatus.PENDING),
        ]
    )
    def test_cooldown_blocks_for_active_statuses(self, _name: str, blocking_status: str) -> None:
        now = datetime(2026, 4, 30, 10, 0, tzinfo=UTC)
        with freeze_time(now - timedelta(minutes=10)):
            self._make_check(investigation_status=blocking_status)

        with freeze_time(now):
            new_check = self._make_check()
            assert not claim_investigation_slot(self.alert, new_check)

    @parameterized.expand(
        [
            ("skipped", InvestigationStatus.SKIPPED),
            ("failed", InvestigationStatus.FAILED),
        ]
    )
    def test_cooldown_ignores_terminal_failure_statuses(self, _name: str, terminal_status: str) -> None:
        now = datetime(2026, 4, 30, 10, 0, tzinfo=UTC)
        with freeze_time(now - timedelta(minutes=10)):
            self._make_check(investigation_status=terminal_status)

        with freeze_time(now):
            new_check = self._make_check()
            assert claim_investigation_slot(self.alert, new_check)
