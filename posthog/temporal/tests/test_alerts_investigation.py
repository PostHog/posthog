"""Tests for the investigation-agent trigger helpers in posthog/temporal/alerts/investigation.py.

The decision logic — should we kick off an investigation, can we claim the cooldown
slot — runs synchronously inside the `evaluate_alert` activity. These tests exercise
the helpers directly so they're independent of Temporal harnessing.
"""

from datetime import UTC, datetime, timedelta

from freezegun import freeze_time
from posthog.test.base import BaseTest

from parameterized import parameterized

from posthog.schema import AlertCalculationInterval, AlertState

from posthog.temporal.alerts.investigation import (
    claim_investigation_slot,
    investigation_cooldown,
    should_trigger_investigation,
)
from posthog.temporal.alerts.retry_policy import alert_timeouts

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration, InvestigationStatus
from products.product_analytics.backend.models.insight import Insight


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

    def test_triggers_on_a_firing_check(self) -> None:
        assert should_trigger_investigation(self.alert, new_state=AlertState.FIRING)

    @parameterized.expand([("not_firing", AlertState.NOT_FIRING), ("errored", AlertState.ERRORED)])
    def test_does_not_trigger_for_non_firing_checks(self, _name: str, new_state: str) -> None:
        assert not should_trigger_investigation(self.alert, new_state=new_state)

    def test_does_not_trigger_when_not_opted_in(self) -> None:
        self.alert.investigation_agent_enabled = False
        self.alert.save()
        assert not should_trigger_investigation(self.alert, new_state=AlertState.FIRING)

    def test_does_not_trigger_for_threshold_only_alerts(self) -> None:
        self.alert.detector_config = None
        self.alert.save()
        assert not should_trigger_investigation(self.alert, new_state=AlertState.FIRING)


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
            calculation_interval=AlertCalculationInterval.DAILY,
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

    def test_skips_a_retried_evaluation_of_the_same_fire(self) -> None:
        now = datetime(2026, 4, 30, 10, 0, tzinfo=UTC)
        with freeze_time(now - timedelta(minutes=1)):
            self._make_check(investigation_status=InvestigationStatus.DONE)

        with freeze_time(now):
            new_check = self._make_check()
            assert not claim_investigation_slot(self.alert, new_check)

        new_check.refresh_from_db()
        assert new_check.investigation_status == InvestigationStatus.SKIPPED

    @parameterized.expand(
        [
            ("daily", AlertCalculationInterval.DAILY, timedelta(hours=24)),
            # Hourly checks land just under an hour apart (each run starts a second or
            # two earlier than the last), so a flat one-hour cooldown would swallow every
            # re-fire and leave its notification un-investigated.
            ("hourly", AlertCalculationInterval.HOURLY, timedelta(minutes=59)),
        ]
    )
    def test_claims_on_the_next_scheduled_check(
        self, _name: str, interval: str, gap_since_last_investigation: timedelta
    ) -> None:
        self.alert.calculation_interval = interval
        self.alert.save()
        now = datetime(2026, 4, 30, 10, 0, tzinfo=UTC)
        with freeze_time(now - gap_since_last_investigation):
            self._make_check(investigation_status=InvestigationStatus.DONE)

        with freeze_time(now):
            new_check = self._make_check()
            assert claim_investigation_slot(self.alert, new_check)

        new_check.refresh_from_db()
        assert new_check.investigation_status == InvestigationStatus.PENDING

    @parameterized.expand(
        [
            ("real_time", AlertCalculationInterval.REAL_TIME),
            ("every_15_minutes", AlertCalculationInterval.EVERY_15_MINUTES),
        ]
    )
    def test_sub_hourly_alerts_investigate_at_most_once_an_hour(self, _name: str, interval: str) -> None:
        # Every investigation is a full agent run, so a real-time alert firing on each
        # check must not queue one per check.
        self.alert.calculation_interval = interval
        self.alert.save()
        now = datetime(2026, 4, 30, 10, 0, tzinfo=UTC)
        with freeze_time(now - timedelta(minutes=30)):
            self._make_check(investigation_status=InvestigationStatus.DONE)

        with freeze_time(now):
            new_check = self._make_check()
            assert not claim_investigation_slot(self.alert, new_check)

        new_check.refresh_from_db()
        assert new_check.investigation_status == InvestigationStatus.SKIPPED

    @parameterized.expand(
        [
            ("running", InvestigationStatus.RUNNING),
            ("done", InvestigationStatus.DONE),
            ("pending", InvestigationStatus.PENDING),
            # A persistent failure would otherwise re-launch a full agent run on every
            # check, since every firing check is now eligible.
            ("failed", InvestigationStatus.FAILED),
        ]
    )
    def test_cooldown_blocks_for_attempted_investigations(self, _name: str, blocking_status: str) -> None:
        now = datetime(2026, 4, 30, 10, 0, tzinfo=UTC)
        with freeze_time(now - timedelta(minutes=1)):
            self._make_check(investigation_status=blocking_status)

        with freeze_time(now):
            new_check = self._make_check()
            assert not claim_investigation_slot(self.alert, new_check)

    def test_cooldown_ignores_a_skipped_check(self) -> None:
        # SKIPPED means no investigation ran, so it must not hold the leash it never took.
        now = datetime(2026, 4, 30, 10, 0, tzinfo=UTC)
        with freeze_time(now - timedelta(minutes=1)):
            self._make_check(investigation_status=InvestigationStatus.SKIPPED)

        with freeze_time(now):
            new_check = self._make_check()
            assert claim_investigation_slot(self.alert, new_check)

    @parameterized.expand(
        [
            ("hourly", AlertCalculationInterval.HOURLY),
            ("real_time", AlertCalculationInterval.REAL_TIME),
        ]
    )
    def test_cooldown_outlives_the_evaluation_retry_window(self, _name: str, interval: str) -> None:
        # evaluate_alert commits its AlertCheck before the activity reports completion, so a
        # worker that dies in between writes a second check on retry — up to
        # activity_schedule_to_close later. The cooldown has to outlast that budget or the
        # retry claims a second investigation for the same fire.
        self.alert.calculation_interval = interval
        assert investigation_cooldown(self.alert) > alert_timeouts(interval).activity_schedule_to_close
