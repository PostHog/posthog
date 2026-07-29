from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from posthog.schema_enums import AlertState as InsightAlertState

from products.alerts.backend.state_machine import (
    AlertCheckOutcome,
    AlertPolicy,
    AlertSnapshot,
    AlertState,
    CheckInput,
    ControlPlaneOutcome,
    NotificationAction,
    Outcome,
    apply_disable as shared_apply_disable,
    apply_enable as shared_apply_enable,
    apply_snooze as shared_apply_snooze,
    apply_threshold_change as shared_apply_threshold_change,
    apply_unsnooze as shared_apply_unsnooze,
    evaluate_alert_check as shared_evaluate_alert_check,
)

if TYPE_CHECKING:
    from products.alerts.backend.models.alert import AlertConfiguration


INSIGHT_ALERT_POLICY = AlertPolicy(
    max_consecutive_failures=None,
    notify_error_on_every_failure=True,
    renotify_while_firing=True,
    notify_resolve=False,
    errors_set_errored_state=True,
)


def snapshot_from_alert(alert: AlertConfiguration) -> AlertSnapshot:
    return AlertSnapshot(
        state=AlertState[InsightAlertState(alert.state).name],
        cooldown=timedelta(0),
        last_notified_at=alert.last_notified_at,
        snooze_until=alert.snoozed_until,
        consecutive_failures=0,
    )


def evaluate_alert_check(
    alert: AlertConfiguration,
    *,
    threshold_breached: bool,
    error_message: str | None,
    now: datetime,
) -> AlertCheckOutcome:
    return shared_evaluate_alert_check(
        snapshot_from_alert(alert),
        CheckInput(threshold_breached=threshold_breached, error_message=error_message),
        now,
        policy=INSIGHT_ALERT_POLICY,
    )


def apply_outcome(alert: AlertConfiguration, outcome: Outcome) -> list[str]:
    alert.state = InsightAlertState[outcome.new_state.name]
    return ["state"]


def apply_enable(alert: AlertConfiguration) -> list[str]:
    alert.enabled = True
    return ["enabled", *apply_outcome(alert, shared_apply_enable(snapshot_from_alert(alert)))]


def apply_disable(alert: AlertConfiguration) -> list[str]:
    alert.enabled = False
    return ["enabled", *apply_outcome(alert, shared_apply_disable(snapshot_from_alert(alert)))]


def apply_snooze(alert: AlertConfiguration) -> list[str]:
    return apply_outcome(alert, shared_apply_snooze(snapshot_from_alert(alert)))


def apply_unsnooze(alert: AlertConfiguration) -> list[str]:
    return apply_outcome(alert, shared_apply_unsnooze(snapshot_from_alert(alert)))


def apply_threshold_change(alert: AlertConfiguration) -> list[str]:
    return apply_outcome(
        alert,
        shared_apply_threshold_change(snapshot_from_alert(alert), preserve_snoozed_state=False),
    )


def apply_invalid_configuration(alert: AlertConfiguration) -> list[str]:
    alert.enabled = False
    return [
        "enabled",
        *apply_outcome(alert, ControlPlaneOutcome(new_state=AlertState.ERRORED, consecutive_failures=0)),
    ]


def should_notify(outcome: AlertCheckOutcome) -> bool:
    return outcome.notification != NotificationAction.NONE
