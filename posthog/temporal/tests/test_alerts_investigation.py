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
    MAX_INVESTIGATIONS_PER_EPISODE,
    claim_investigation_slot,
    decide_investigation,
    investigation_cooldown,
)

from products.alerts.backend.investigation_episode import episode_investigations
from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration, InvestigationStatus
from products.product_analytics.backend.facade.models import Insight

_EPISODE_START = datetime(2026, 4, 30, 6, 0, tzinfo=UTC)


class InvestigationTestCase(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="test insight")
        self.alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=self.insight,
            name="anomaly alert",
            detector_config={"type": "zscore", "threshold": 0.95, "window": 30},
            investigation_agent_enabled=True,
            calculation_interval=AlertCalculationInterval.HOURLY,
        )

    def _make_check(
        self,
        *,
        at: datetime,
        state: str = AlertState.FIRING,
        investigation_status: str | None = None,
        investigation_verdict: str | None = None,
    ) -> AlertCheck:
        with freeze_time(at):
            return AlertCheck.objects.create(
                alert_configuration=self.alert,
                state=state,
                calculated_value=42.0,
                investigation_status=investigation_status,
                investigation_verdict=investigation_verdict,
            )

    def _firing_episode(self, *, investigated: int) -> AlertCheck:
        """Write a NOT_FIRING check, then `investigated` investigated firing checks,
        then the current firing check, one hour apart."""
        self._make_check(at=_EPISODE_START, state=AlertState.NOT_FIRING)
        for index in range(investigated):
            self._make_check(
                at=_EPISODE_START + timedelta(hours=index + 1),
                investigation_status=InvestigationStatus.DONE,
                investigation_verdict="true_positive",
            )
        return self._make_check(at=_EPISODE_START + timedelta(hours=investigated + 1))


class TestDecideInvestigation(InvestigationTestCase):
    @parameterized.expand([("first", 0), ("second", 1), ("third", MAX_INVESTIGATIONS_PER_EPISODE - 1)])
    def test_investigates_every_firing_check_inside_the_budget(self, _name: str, already_investigated: int) -> None:
        check = self._firing_episode(investigated=already_investigated)

        decision = decide_investigation(self.alert, check)

        assert decision.should_investigate
        assert decision.is_first_of_episode is (already_investigated == 0)

    def test_stops_once_the_budget_is_spent(self) -> None:
        check = self._firing_episode(investigated=MAX_INVESTIGATIONS_PER_EPISODE)

        assert not decide_investigation(self.alert, check).should_investigate

    def test_investigates_a_check_whose_predecessor_was_dismissed(self) -> None:
        # The suppressed-false-positive case needs no rule of its own: the next check is
        # simply the episode's second, and the budget lets it through.
        self._make_check(at=_EPISODE_START, state=AlertState.NOT_FIRING)
        self._make_check(
            at=_EPISODE_START + timedelta(hours=1),
            investigation_status=InvestigationStatus.DONE,
            investigation_verdict="false_positive",
        )
        check = self._make_check(at=_EPISODE_START + timedelta(hours=2))

        decision = decide_investigation(self.alert, check)

        assert decision.should_investigate
        assert not decision.is_first_of_episode

    def test_budget_resets_after_the_alert_stops_firing(self) -> None:
        self._firing_episode(investigated=MAX_INVESTIGATIONS_PER_EPISODE)
        self._make_check(at=_EPISODE_START + timedelta(hours=12), state=AlertState.NOT_FIRING)
        check = self._make_check(at=_EPISODE_START + timedelta(hours=13))

        decision = decide_investigation(self.alert, check)

        assert decision.should_investigate
        assert decision.is_first_of_episode

    def test_a_skipped_check_does_not_spend_budget(self) -> None:
        # SKIPPED means the cooldown refused the slot, so no agent ever ran.
        self._make_check(at=_EPISODE_START, state=AlertState.NOT_FIRING)
        for index in range(MAX_INVESTIGATIONS_PER_EPISODE):
            self._make_check(
                at=_EPISODE_START + timedelta(hours=index + 1),
                investigation_status=InvestigationStatus.SKIPPED,
            )
        check = self._make_check(at=_EPISODE_START + timedelta(hours=MAX_INVESTIGATIONS_PER_EPISODE + 1))

        assert decide_investigation(self.alert, check).should_investigate

    @parameterized.expand([("not_firing", AlertState.NOT_FIRING), ("errored", AlertState.ERRORED)])
    def test_does_not_trigger_on_a_check_that_is_not_firing(self, _name: str, state: str) -> None:
        check = self._make_check(at=_EPISODE_START + timedelta(hours=1), state=state)

        assert not decide_investigation(self.alert, check).should_investigate

    def test_does_not_trigger_when_not_opted_in(self) -> None:
        self.alert.investigation_agent_enabled = False
        self.alert.save()
        check = self._make_check(at=_EPISODE_START + timedelta(hours=1))

        assert not decide_investigation(self.alert, check).should_investigate

    def test_does_not_trigger_for_threshold_only_alerts(self) -> None:
        self.alert.detector_config = None
        self.alert.save()
        check = self._make_check(at=_EPISODE_START + timedelta(hours=1))

        assert not decide_investigation(self.alert, check).should_investigate


class TestEpisodeInvestigations(InvestigationTestCase):
    def test_reports_the_previous_verdict_and_the_episode_key(self) -> None:
        self._make_check(at=_EPISODE_START, state=AlertState.NOT_FIRING)
        first = self._make_check(
            at=_EPISODE_START + timedelta(hours=1),
            investigation_status=InvestigationStatus.DONE,
            investigation_verdict="false_positive",
        )
        second = self._make_check(
            at=_EPISODE_START + timedelta(hours=2),
            investigation_status=InvestigationStatus.DONE,
            investigation_verdict="true_positive",
        )

        episode = episode_investigations(self.alert, second)

        assert episode.previous_verdict == "false_positive"
        # Every investigation of one incident emits under the same signal source id.
        assert episode.first_check_id == str(first.id)
        assert episode.is_first is False

    def test_a_verdict_from_the_previous_episode_is_not_carried_over(self) -> None:
        self._make_check(
            at=_EPISODE_START,
            investigation_status=InvestigationStatus.DONE,
            investigation_verdict="true_positive",
        )
        self._make_check(at=_EPISODE_START + timedelta(hours=1), state=AlertState.NOT_FIRING)
        check = self._make_check(at=_EPISODE_START + timedelta(hours=2))

        episode = episode_investigations(self.alert, check)

        assert episode.previous_verdict is None
        assert episode.first_check_id == str(check.id)
        assert episode.is_first


class TestInvestigationCooldown(InvestigationTestCase):
    @parameterized.expand(
        [
            ("real_time", AlertCalculationInterval.REAL_TIME, timedelta(minutes=5)),
            ("every_15_minutes", AlertCalculationInterval.EVERY_15_MINUTES, timedelta(minutes=10)),
            # An hourly alert's next check must clear the cooldown, or scheduler jitter
            # decides whether the episode's second investigation runs.
            ("hourly", AlertCalculationInterval.HOURLY, timedelta(minutes=55)),
            ("daily", AlertCalculationInterval.DAILY, timedelta(hours=1)),
        ]
    )
    def test_cooldown_follows_the_calculation_interval(self, _name: str, interval: str, expected: timedelta) -> None:
        self.alert.calculation_interval = interval
        self.alert.save()

        assert investigation_cooldown(self.alert) == expected

    def test_hourly_alert_can_investigate_its_next_check(self) -> None:
        self._make_check(at=_EPISODE_START, investigation_status=InvestigationStatus.DONE)
        check = self._make_check(at=_EPISODE_START + timedelta(hours=1))

        with freeze_time(_EPISODE_START + timedelta(hours=1)):
            assert claim_investigation_slot(self.alert, check)


class TestClaimInvestigationSlot(InvestigationTestCase):
    def test_claims_when_no_recent_investigation(self) -> None:
        check = self._make_check(at=_EPISODE_START)

        with freeze_time(_EPISODE_START):
            assert claim_investigation_slot(self.alert, check)

        check.refresh_from_db()
        assert check.investigation_status == InvestigationStatus.PENDING

    def test_skips_when_recent_investigation_exists(self) -> None:
        now = datetime(2026, 4, 30, 10, 0, tzinfo=UTC)
        self._make_check(at=now - timedelta(minutes=10), investigation_status=InvestigationStatus.DONE)
        new_check = self._make_check(at=now)

        with freeze_time(now):
            assert not claim_investigation_slot(self.alert, new_check)

        new_check.refresh_from_db()
        assert new_check.investigation_status == InvestigationStatus.SKIPPED

    def test_claims_after_cooldown_expires(self) -> None:
        now = datetime(2026, 4, 30, 10, 0, tzinfo=UTC)
        self._make_check(at=now - timedelta(hours=2), investigation_status=InvestigationStatus.DONE)
        new_check = self._make_check(at=now)

        with freeze_time(now):
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
        self._make_check(at=now - timedelta(minutes=10), investigation_status=blocking_status)
        new_check = self._make_check(at=now)

        with freeze_time(now):
            assert not claim_investigation_slot(self.alert, new_check)

    @parameterized.expand(
        [
            ("skipped", InvestigationStatus.SKIPPED),
            ("failed", InvestigationStatus.FAILED),
        ]
    )
    def test_cooldown_ignores_terminal_failure_statuses(self, _name: str, terminal_status: str) -> None:
        now = datetime(2026, 4, 30, 10, 0, tzinfo=UTC)
        self._make_check(at=now - timedelta(minutes=10), investigation_status=terminal_status)
        new_check = self._make_check(at=now)

        with freeze_time(now):
            assert claim_investigation_slot(self.alert, new_check)
