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

from posthog.temporal.alerts.investigation import claim_investigation_slot, should_trigger_investigation

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


class TestShouldTriggerInvestigationPostHogCode(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="test insight")

    def _alert(self, **kwargs) -> AlertConfiguration:
        defaults: dict = {
            "investigation_agent_enabled": True,
            "investigation_mode": AlertConfiguration.InvestigationMode.POSTHOG_CODE,
            "investigation_rerun_on_continued_breach": True,
            "detector_config": None,
        }
        defaults.update(kwargs)
        return AlertConfiguration(team=self.team, insight=self.insight, **defaults)

    @parameterized.expand(
        [
            ("threshold_transition", None, AlertState.FIRING, True),
            ("from_not_firing", AlertState.NOT_FIRING, AlertState.FIRING, True),
            ("still_firing_rerun_on", AlertState.FIRING, AlertState.FIRING, True),
            ("resolves", AlertState.FIRING, AlertState.NOT_FIRING, False),
            ("errored", None, AlertState.ERRORED, False),
        ]
    )
    def test_posthog_code_transitions(self, _name, previous_state, new_state, expected) -> None:
        alert = self._alert()
        assert should_trigger_investigation(alert, previous_state=previous_state, new_state=new_state) is expected

    def test_still_firing_requires_rerun_toggle(self) -> None:
        alert = self._alert(investigation_rerun_on_continued_breach=False)
        assert (
            should_trigger_investigation(alert, previous_state=AlertState.FIRING, new_state=AlertState.FIRING) is False
        )

    def test_disabled_never_triggers(self) -> None:
        alert = self._alert(investigation_agent_enabled=False)
        assert should_trigger_investigation(alert, previous_state=None, new_state=AlertState.FIRING) is False

    def test_notebook_mode_unchanged_still_requires_detector(self) -> None:
        alert = self._alert(investigation_mode=AlertConfiguration.InvestigationMode.NOTEBOOK)
        assert should_trigger_investigation(alert, previous_state=None, new_state=AlertState.FIRING) is False


class TestClaimInvestigationSlotPostHogCode(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.insight = Insight.objects.create(team=self.team, name="test insight")
        self.alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=self.insight,
            name="posthog code alert",
            detector_config=None,
            investigation_agent_enabled=True,
            investigation_mode=AlertConfiguration.InvestigationMode.POSTHOG_CODE,
            investigation_rerun_on_continued_breach=True,
        )

    def _make_check(
        self, alert: AlertConfiguration, *, state: str, investigation_status: str | None = None, created_at: datetime
    ) -> AlertCheck:
        check = AlertCheck.objects.create(
            alert_configuration=alert,
            calculated_value=0,
            state=state,
            targets_notified={},
            investigation_status=investigation_status,
        )
        AlertCheck.objects.filter(id=check.id).update(created_at=created_at)
        return check

    @parameterized.expand(
        [
            ("posthog_code_blocks", AlertConfiguration.InvestigationMode.POSTHOG_CODE, False),
            ("notebook_ignores", AlertConfiguration.InvestigationMode.NOTEBOOK, True),
        ]
    )
    def test_failed_occupies_slot_by_mode(self, _name, mode, expected_claim) -> None:
        alert = AlertConfiguration.objects.create(
            team=self.team,
            insight=self.insight,
            name=f"alert {_name}",
            investigation_agent_enabled=True,
            investigation_mode=mode,
            detector_config={"type": "zscore", "threshold": 0.95, "window": 30}
            if mode == AlertConfiguration.InvestigationMode.NOTEBOOK
            else None,
        )
        now = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
        self._make_check(
            alert,
            state=AlertState.FIRING,
            investigation_status=InvestigationStatus.FAILED,
            created_at=now - timedelta(minutes=30),
        )
        with freeze_time(now):
            new_check = self._make_check(alert, state=AlertState.FIRING, investigation_status=None, created_at=now)
            assert claim_investigation_slot(alert, new_check) is expected_claim

    def test_active_run_always_occupies(self) -> None:
        now = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
        self._make_check(
            self.alert,
            state=AlertState.FIRING,
            investigation_status=InvestigationStatus.PENDING,
            created_at=now - timedelta(hours=3),
        )
        with freeze_time(now):
            new_check = self._make_check(self.alert, state=AlertState.FIRING, investigation_status=None, created_at=now)
            assert claim_investigation_slot(self.alert, new_check) is False

    @parameterized.expand(
        [
            # (n_completed, minutes_after_episode_start, expect_claim)
            # All DONE checks are placed at episode_start (T=0); cooldown = 1h * 2^N.
            # Slot is blocked while now - T < cooldown, i.e. minutes < 60*2^N.
            # N=1: cooldown=2h → blocked <120min, free >=120min
            ("n1_still_blocked", 1, 119, False),
            ("n1_just_free", 1, 121, True),
            # N=2: cooldown=4h → blocked <240min, free >=240min
            ("n2_still_blocked", 2, 239, False),
            ("n2_just_free", 2, 241, True),
        ]
    )
    def test_backoff_progression(self, _name, n_completed, minutes_after_episode_start, expect_claim) -> None:
        # All completed checks are placed at T=0 (episode_start) for simplicity;
        # what matters is the count, not their spread.
        episode_start = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
        for _ in range(n_completed):
            self._make_check(
                self.alert,
                state=AlertState.FIRING,
                investigation_status=InvestigationStatus.DONE,
                created_at=episode_start,
            )
        now = episode_start + timedelta(minutes=minutes_after_episode_start)
        with freeze_time(now):
            new_check = self._make_check(self.alert, state=AlertState.FIRING, investigation_status=None, created_at=now)
            assert claim_investigation_slot(self.alert, new_check) is expect_claim

    def test_backoff_cap_at_24h(self) -> None:
        # N=6 would give 2^6=64h, but cap at 24h; 25h after last done should be free.
        episode_start = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
        for _ in range(6):
            self._make_check(
                self.alert,
                state=AlertState.FIRING,
                investigation_status=InvestigationStatus.DONE,
                created_at=episode_start,
            )
        now = episode_start + timedelta(hours=25)
        with freeze_time(now):
            new_check = self._make_check(self.alert, state=AlertState.FIRING, investigation_status=None, created_at=now)
            assert claim_investigation_slot(self.alert, new_check) is True

    def test_backoff_resets_after_resolve(self) -> None:
        episode_start = datetime(2026, 5, 1, 0, 0, tzinfo=UTC)
        for i in range(3):
            self._make_check(
                self.alert,
                state=AlertState.FIRING,
                investigation_status=InvestigationStatus.DONE,
                created_at=episode_start + timedelta(hours=i),
            )
        resolve_time = episode_start + timedelta(hours=3)
        self._make_check(self.alert, state=AlertState.NOT_FIRING, investigation_status=None, created_at=resolve_time)
        now = resolve_time + timedelta(minutes=70)
        with freeze_time(now):
            new_check = self._make_check(self.alert, state=AlertState.FIRING, investigation_status=None, created_at=now)
            assert claim_investigation_slot(self.alert, new_check) is True
