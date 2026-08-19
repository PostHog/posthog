from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import cast

from posthog.schema_enums import AlertState as InsightAlertState

from products.alerts.backend.insight_alert_state_machine import (
    apply_disable,
    apply_enable,
    apply_snooze,
    apply_threshold_change,
    apply_unsnooze,
    disable_if_target_date_passed,
    evaluate_alert_check,
    should_notify,
)
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts.backend.state_machine import AlertState

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)


def alert_with_state(state: InsightAlertState, *, enabled: bool = True) -> AlertConfiguration:
    return cast(
        AlertConfiguration,
        SimpleNamespace(enabled=enabled, state=state.value, last_notified_at=None, snoozed_until=None),
    )


def test_repeated_breach_stays_firing_and_notifies() -> None:
    outcome = evaluate_alert_check(
        alert_with_state(InsightAlertState.FIRING), threshold_breached=True, error_message=None, now=NOW
    )

    assert outcome.new_state == AlertState.FIRING
    assert should_notify(outcome)


def test_clear_check_resolves_without_notification() -> None:
    outcome = evaluate_alert_check(
        alert_with_state(InsightAlertState.FIRING), threshold_breached=False, error_message=None, now=NOW
    )

    assert outcome.new_state == AlertState.NOT_FIRING
    assert not should_notify(outcome)


def test_error_notifies_once_until_a_successful_check_resets_the_streak() -> None:
    alert = alert_with_state(InsightAlertState.NOT_FIRING)

    first_failure = evaluate_alert_check(alert, threshold_breached=False, error_message="query failed", now=NOW)
    assert first_failure.new_state == AlertState.ERRORED
    assert should_notify(first_failure)

    alert.state = InsightAlertState.ERRORED
    repeated_failure = evaluate_alert_check(alert, threshold_breached=False, error_message="query failed", now=NOW)
    assert repeated_failure.new_state == AlertState.ERRORED
    assert not should_notify(repeated_failure)

    recovery = evaluate_alert_check(alert, threshold_breached=False, error_message=None, now=NOW)
    assert recovery.new_state == AlertState.NOT_FIRING

    alert.state = InsightAlertState.NOT_FIRING
    new_failure = evaluate_alert_check(alert, threshold_breached=False, error_message="query failed", now=NOW)
    assert should_notify(new_failure)


def test_control_plane_transitions_use_shared_outcomes() -> None:
    alert = alert_with_state(InsightAlertState.FIRING)

    assert apply_snooze(alert) == ["state"]
    assert alert.state == InsightAlertState.SNOOZED
    assert apply_threshold_change(alert) == ["state"]
    assert alert.state == InsightAlertState.NOT_FIRING
    apply_snooze(alert)
    assert apply_unsnooze(alert) == ["state"]
    assert alert.state == InsightAlertState.NOT_FIRING
    assert apply_disable(alert) == ["enabled", "state"]
    assert alert.enabled is False

    disabled_alert = alert_with_state(InsightAlertState.NOT_FIRING, enabled=False)
    assert apply_enable(disabled_alert) == ["enabled", "state"]
    assert disabled_alert.enabled is True
    assert disabled_alert.state == InsightAlertState.NOT_FIRING


class TestTargetDatePassed:
    def _alert(self, target_date: str) -> AlertConfiguration:
        return AlertConfiguration(
            name="target alert",
            enabled=True,
            state=InsightAlertState.NOT_FIRING,
            condition={"type": "absolute_value"},
            config={"type": "TrendsAlertConfig", "series_index": 0},
            calculation_interval="daily",
            forecast_config={
                "type": "ForecastConfig",
                "engine": "prophet",
                "condition": "target_by_date",
                "target": 100,
                "target_direction": "at_least",
                "target_date": target_date,
            },
        )

    def test_disables_once_the_date_passes(self) -> None:
        alert = self._alert("2026-01-01")
        changed = disable_if_target_date_passed(alert, today=date(2026, 1, 2))
        assert alert.enabled is False
        assert "enabled" in changed

    def test_disables_on_the_date_itself(self) -> None:
        alert = self._alert("2026-01-01")
        assert disable_if_target_date_passed(alert, today=date(2026, 1, 1)) != []
        assert alert.enabled is False

    def test_stays_enabled_before_the_date(self) -> None:
        alert = self._alert("2026-01-01")
        assert disable_if_target_date_passed(alert, today=date(2025, 12, 31)) == []
        assert alert.enabled is True

    def test_ignores_the_other_conditions(self) -> None:
        alert = self._alert("2026-01-01")
        alert.forecast_config = {"type": "ForecastConfig", "engine": "prophet", "condition": "future_breach"}
        assert disable_if_target_date_passed(alert, today=date(2030, 1, 1)) == []
        assert alert.enabled is True

    def test_ignores_an_alert_with_no_forecast_config(self) -> None:
        alert = self._alert("2026-01-01")
        alert.forecast_config = None
        assert disable_if_target_date_passed(alert, today=date(2030, 1, 1)) == []
