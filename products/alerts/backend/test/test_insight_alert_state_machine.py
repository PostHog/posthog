from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest

from posthog.schema_enums import AlertState as InsightAlertState

from products.alerts.backend.insight_alert_state_machine import (
    apply_disable,
    apply_enable,
    apply_snooze,
    apply_threshold_change,
    apply_unsnooze,
    evaluate_alert_check,
    is_firing_not_renotified,
    should_notify,
)
from products.alerts.backend.models.alert import AlertConfiguration
from products.alerts_platform.backend.facade.lifecycle import AlertState

NOW = datetime(2026, 7, 27, 12, 0, tzinfo=UTC)
AI_DETECTOR = {"type": "llm"}


def alert_with_state(
    state: InsightAlertState,
    *,
    enabled: bool = True,
    detector_config: dict[str, Any] | None = None,
    snoozed_until: datetime | None = None,
) -> AlertConfiguration:
    return cast(
        AlertConfiguration,
        SimpleNamespace(
            enabled=enabled,
            state=state.value,
            last_notified_at=None,
            snoozed_until=snoozed_until,
            detector_config=detector_config,
        ),
    )


@pytest.mark.parametrize(
    "detector_config,renotifies",
    [
        (None, True),
        ({"type": "zscore", "threshold": 0.9, "window": 30}, True),
        (AI_DETECTOR, False),
    ],
)
def test_repeated_breach_stays_firing_and_renotifies_only_for_statistical_alerts(
    detector_config: dict[str, Any] | None, renotifies: bool
) -> None:
    outcome = evaluate_alert_check(
        alert_with_state(InsightAlertState.FIRING, detector_config=detector_config),
        threshold_breached=True,
        error_message=None,
        now=NOW,
    )

    assert outcome.new_state == AlertState.FIRING
    assert should_notify(outcome) is renotifies
    assert is_firing_not_renotified(outcome) is not renotifies


def test_ai_detector_alert_announces_each_firing_episode_once() -> None:
    alert = alert_with_state(InsightAlertState.NOT_FIRING, detector_config=AI_DETECTOR)
    announced = []
    for breached in (True, True, True, False, True, True):
        outcome = evaluate_alert_check(alert, threshold_breached=breached, error_message=None, now=NOW)
        alert.state = InsightAlertState[outcome.new_state.name]
        announced.append(should_notify(outcome))

    assert announced == [True, False, False, False, True, False]


def test_ai_detector_alert_announces_a_firing_that_outlasts_its_snooze() -> None:
    alert = alert_with_state(
        InsightAlertState.SNOOZED, detector_config=AI_DETECTOR, snoozed_until=NOW - timedelta(minutes=1)
    )

    outcome = evaluate_alert_check(alert, threshold_breached=True, error_message=None, now=NOW)

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
