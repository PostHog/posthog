"""Investigation-agent trigger helpers used by the Temporal evaluate_alert activity.

The trigger and notification-gating decisions both run inside `evaluate_alert`
in the same DB transaction as the AlertCheck insert, so the read-then-write that
claims the cooldown lease stays consistent. This module exposes the primitives
as pure functions so they can be unit-tested independently of Temporal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from posthog.schema import AlertState

from products.alerts.backend.models.alert import AlertCheck, AlertConfiguration, InvestigationStatus

# Hourly and slower alerts get an investigation per firing check. The guard only has to
# separate a retried or concurrent evaluation of the same check — those land seconds
# apart — from the next scheduled check an hour or more later.
INVESTIGATION_COOLDOWN = timedelta(minutes=5)

# Sub-hourly alerts (real time, every 15 minutes) can fire many times an hour and each
# investigation is a full agent run, so they stay on an hourly leash instead.
HIGH_FREQUENCY_INVESTIGATION_COOLDOWN = timedelta(hours=1)


def investigation_cooldown(alert: AlertConfiguration) -> timedelta:
    """Minimum spacing between two investigations of the same alert."""
    return HIGH_FREQUENCY_INVESTIGATION_COOLDOWN if alert.is_high_frequency_interval else INVESTIGATION_COOLDOWN


def should_trigger_investigation(alert: AlertConfiguration, *, new_state: str) -> bool:
    """True when this fire is eligible for an investigation, ignoring cooldown.

    Every firing check is eligible, not just the transition into FIRING: an alert that
    stays firing keeps producing notifications, and each one needs its own verdict to
    gate on. Frequency is bounded by `claim_investigation_slot`, which does the
    read-then-write inside the caller's transaction.
    """
    if not alert.investigation_agent_enabled:
        return False
    if not alert.detector_config:
        return False
    if new_state != AlertState.FIRING:
        return False
    return True


def claim_investigation_slot(alert: AlertConfiguration, alert_check: AlertCheck) -> bool:
    """Try to claim the cooldown slot for `alert` and return True on success.

    On success, marks `alert_check.investigation_status = PENDING`. On failure
    (a recent investigation is RUNNING/DONE/PENDING within the cooldown window),
    marks it SKIPPED and returns False so flappy alerts don't pile up.

    Caller must run this inside a transaction so the read-then-write is atomic.
    """
    cooldown_since = datetime.now(UTC) - investigation_cooldown(alert)
    recent = AlertCheck.objects.filter(
        alert_configuration=alert,
        created_at__gte=cooldown_since,
        investigation_status__in=[
            InvestigationStatus.RUNNING,
            InvestigationStatus.DONE,
            InvestigationStatus.PENDING,
        ],
    ).exclude(id=alert_check.id)
    if recent.exists():
        AlertCheck.objects.filter(id=alert_check.id).update(investigation_status=InvestigationStatus.SKIPPED)
        return False
    AlertCheck.objects.filter(id=alert_check.id).update(investigation_status=InvestigationStatus.PENDING)
    return True
