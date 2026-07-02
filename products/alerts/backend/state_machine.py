"""Insight alert adapter for the shared alert lifecycle machine.

The decision logic lives in common/alerting/state_machine.py, configured with
INSIGHT_ALERT_POLICY. Insight alerts store their state with the legacy
posthog.schema AlertState string values ("Firing", "Not firing", ...), so this
module owns the enum mapping at the boundary; the check-driven transition in
posthog/tasks/alerts/utils.py routes through decide_insight_alert_check.

Control-plane transitions (snooze/unsnooze in the API, disable in the model's
save hook, snooze-expiry in the prepare activity) still assign state inline —
they predate the shared machine and match its apply_* semantics one-to-one.

One deliberate divergence from the pre-adapter logic: an alert evaluated while
SNOOZED with an active `snoozed_until` now stays SNOOZED silently, where the old
inline code would set FIRING/ERRORED and notify. That window is unreachable in
the scheduled path (the prepare activity skips actively-snoozed alerts and clears
expired snoozes before evaluation) and the new behavior is the safe direction.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from posthog.schema_enums import AlertState

from common.alerting.state_machine import (
    INSIGHT_ALERT_POLICY,
    AlertSnapshot as SharedAlertSnapshot,
    AlertState as SharedAlertState,
    CheckInput,
    NotificationAction,
    evaluate_alert_check,
)

if TYPE_CHECKING:
    from products.alerts.backend.models.alert import AlertConfiguration

_TO_SHARED_STATE: dict[AlertState, SharedAlertState] = {
    AlertState.FIRING: SharedAlertState.FIRING,
    AlertState.NOT_FIRING: SharedAlertState.NOT_FIRING,
    AlertState.ERRORED: SharedAlertState.ERRORED,
    AlertState.SNOOZED: SharedAlertState.SNOOZED,
}
_FROM_SHARED_STATE: dict[SharedAlertState, AlertState] = {shared: legacy for legacy, shared in _TO_SHARED_STATE.items()}


def decide_insight_alert_check(
    alert: AlertConfiguration,
    *,
    threshold_breached: bool,
    error_message: str | None,
    now: datetime,
) -> tuple[AlertState, bool]:
    """Decide (new_state, notify) for one insight alert check."""
    outcome = evaluate_alert_check(
        SharedAlertSnapshot(
            state=_TO_SHARED_STATE[AlertState(alert.state)],
            cooldown=timedelta(0),
            last_notified_at=alert.last_notified_at,
            snooze_until=alert.snoozed_until,
            consecutive_failures=0,
        ),
        CheckInput(threshold_breached=threshold_breached, error_message=error_message),
        now,
        policy=INSIGHT_ALERT_POLICY,
    )
    return _FROM_SHARED_STATE[outcome.new_state], outcome.notification != NotificationAction.NONE
