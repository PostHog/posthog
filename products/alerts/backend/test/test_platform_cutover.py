from datetime import UTC, datetime, timedelta
from typing import Any

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models import Team
from posthog.models.scoping import team_scope
from posthog.schema_enums import AlertCalculationInterval, AlertState

from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.platform_cutover import CutoverSkip, RollbackSkip, cut_over_team, roll_back_team
from products.alerts.backend.test.insight_alerts import create_insight_alert
from products.alerts_platform.backend.facade import testing as platform_testing
from products.alerts_platform.backend.facade.contracts import DeliveryPath

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
_CUTOVER = "products.alerts.backend.platform_cutover"


class TestInsightPlatformCutover(APIBaseTest):
    def _alert(self, **overrides: Any) -> AlertConfiguration:
        return create_insight_alert(
            self.team,
            **{"next_check_at": NOW + timedelta(minutes=3), "last_notified_at": NOW - timedelta(days=1), **overrides},
        )

    @parameterized.expand(
        [
            ("quiet", {}, "not_firing"),
            ("errored", {"state": AlertState.ERRORED}, "errored"),
            (
                "snoozed_keeps_checking_muted",
                {"state": AlertState.SNOOZED, "snoozed_until": NOW + timedelta(hours=1)},
                "not_firing",
            ),
            ("disabled", {"enabled": False, "next_check_at": None}, "not_firing"),
        ]
    )
    def test_an_alert_moves_with_its_state_and_schedule(
        self, _name: str, overrides: dict[str, Any], platform_state: str
    ) -> None:
        alert = self._alert(**overrides)

        (result,) = cut_over_team(self.team.id, now=NOW)

        assert result.skipped is None
        alert.refresh_from_db()
        assert (alert.owner, alert.owner_changed_at) == ("platform", NOW)
        with team_scope(self.team.id):
            copy = platform_testing.copy_of(alert.id)
            instance = platform_testing.alert_for(copy.id)
        assert (copy.owner, copy.next_check_at) == (
            "platform",
            max(alert.next_check_at or NOW, NOW + timedelta(minutes=1)),
        )
        assert instance is not None
        assert (instance.state, instance.last_notified_at) == (platform_state, alert.last_notified_at)

    @parameterized.expand(
        [
            ("firing", {"state": AlertState.FIRING}, CutoverSkip.FIRING),
            ("check_due", {"next_check_at": NOW}, CutoverSkip.CHECK_DUE),
            ("never_scheduled", {"next_check_at": None}, CutoverSkip.CHECK_DUE),
            ("detector", {"detector_config": {"type": "zscore"}}, CutoverSkip.NOT_ON_PLATFORM),
            (
                "real_time",
                {"calculation_interval": AlertCalculationInterval.REAL_TIME.value},
                CutoverSkip.NOT_ON_PLATFORM,
            ),
            ("investigated", {"investigation_agent_enabled": True}, CutoverSkip.INVESTIGATION),
        ]
    )
    def test_an_alert_that_cannot_move_now_stays_with_insight(
        self, _name: str, overrides: dict[str, Any], reason: CutoverSkip
    ) -> None:
        alert = self._alert(**overrides)

        (result,) = cut_over_team(self.team.id, now=NOW)

        assert result.skipped == reason
        alert.refresh_from_db()
        assert alert.owner == "source"

    def test_an_alert_in_a_child_environment_stays_with_insight(self) -> None:
        environment = Team.objects.create(organization=self.organization, parent_team=self.team, name="env")
        alert = create_insight_alert(environment, next_check_at=NOW + timedelta(minutes=3))

        (result,) = cut_over_team(environment.id, now=NOW)

        assert result.skipped == CutoverSkip.ENVIRONMENT
        alert.refresh_from_db()
        assert alert.owner == "source"

    @parameterized.expand([("events_emitted", True, None), ("nothing_emits", False, CutoverSkip.NO_HOG_FUNCTION_PATH)])
    def test_an_alert_on_the_hog_function_path_moves_only_while_its_events_are_emitted(
        self, _name: str, emitter: bool, reason: CutoverSkip | None
    ) -> None:
        alert = self._alert()

        with (
            patch(f"{_CUTOVER}.choose_delivery_path", return_value=DeliveryPath.HOG_FUNCTION),
            patch(f"{_CUTOVER}.has_legacy_event_emitter", return_value=emitter),
        ):
            (result,) = cut_over_team(self.team.id, now=NOW)

        assert result.skipped == reason
        alert.refresh_from_db()
        assert alert.owner == ("source" if reason else "platform")

    def test_a_second_run_leaves_a_moved_alert_alone(self) -> None:
        self._alert()
        cut_over_team(self.team.id, now=NOW)

        (result,) = cut_over_team(self.team.id, now=NOW + timedelta(minutes=1))

        assert result.skipped == CutoverSkip.ALREADY_MOVED

    def _moved(self, **overrides: Any) -> AlertConfiguration:
        alert = self._alert(**overrides)
        cut_over_team(self.team.id, now=NOW)
        alert.refresh_from_db()
        return alert

    @parameterized.expand(
        [
            ("quiet", {}, None, False, AlertState.NOT_FIRING),
            ("errored", {"state": AlertState.ERRORED}, None, False, AlertState.ERRORED),
            # A snooze lives on the insight alert, so one set after the move survives the handback.
            ("snoozed_since", {}, NOW + timedelta(days=30), False, AlertState.SNOOZED),
            # The insight stack must not resume an alert the platform stopped.
            ("switched_off_by_the_platform", {"state": AlertState.ERRORED}, None, True, AlertState.ERRORED),
        ]
    )
    def test_rolling_back_after_the_shadow_carries_the_platform_state_back(
        self,
        _name: str,
        overrides: dict[str, Any],
        snoozed_until: datetime | None,
        switched_off: bool,
        state: AlertState,
    ) -> None:
        alert = self._moved(**overrides)
        if snoozed_until is not None:
            AlertConfiguration.objects.filter(id=alert.id).update(snoozed_until=snoozed_until)
        if switched_off:
            with team_scope(self.team.id):
                platform_testing.set_enabled(platform_testing.copy_of(alert.id).id, False)
        later = NOW + timedelta(days=8)
        with team_scope(self.team.id):
            platform_testing.set_due_at(platform_testing.copy_of(alert.id).id, later + timedelta(minutes=2))

        (result,) = roll_back_team(self.team.id, now=later)

        assert result.skipped is None
        alert.refresh_from_db()
        assert (alert.owner, alert.owner_changed_at, alert.state, alert.next_check_at, alert.enabled) == (
            "source",
            later,
            state,
            later + timedelta(minutes=2),
            not switched_off,
        )
        with team_scope(self.team.id):
            assert platform_testing.copy_of(alert.id).owner == "source"

    @parameterized.expand(
        [
            ("never_moved", False, NOW + timedelta(days=8), RollbackSkip.NOT_MOVED),
            ("insight_check_due_during_shadow", True, NOW + timedelta(minutes=10), RollbackSkip.INSIGHT_CHECK_DUE),
        ]
    )
    def test_an_alert_that_cannot_move_back_now_stays(
        self, _name: str, moved: bool, at: datetime, reason: RollbackSkip
    ) -> None:
        alert = self._moved() if moved else self._alert()

        (result,) = roll_back_team(self.team.id, now=at)

        assert result.skipped == reason
        alert.refresh_from_db()
        assert alert.owner == ("platform" if moved else "source")
