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

# Hourly and slower alerts get an investigation per firing check. The guard separates a
# retried or concurrent evaluation of the same fire from the next scheduled check, so it
# must outlive `evaluate_alert`'s retry window: a worker that dies after committing its
# AlertCheck writes a second one on retry, up to `activity_schedule_to_close` later.
# `test_cooldown_outlives_the_evaluation_retry_window` holds this above that budget.
#
# A wall clock can't separate the two cases perfectly. Hourly slots advance from the
# previous `next_check_at`, not from completion (`products/alerts/backend/scheduling.py`),
# so an alert evaluated more than an hour-minus-this-window late runs its next slot inside
# the window and gets SKIPPED — which under gating notifies without a verdict. Widening
# this value shrinks that headroom, narrowing it lets a hung-then-retried evaluation claim
# twice. Fixing it properly needs slot identity on the check rather than a time window.
INVESTIGATION_COOLDOWN = timedelta(minutes=15)

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
    (a recent investigation was attempted within the cooldown window), marks it
    SKIPPED and returns False so flappy alerts don't pile up.

    FAILED counts as an attempt: the investigation workflow already retries its own
    activity, so a failure that outlived those retries is a persistent one, and letting
    the next check re-attempt immediately would spend the leash on a loop. SKIPPED does
    not count — no investigation ran, so nothing was spent.

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
            InvestigationStatus.FAILED,
        ],
    ).exclude(id=alert_check.id)
    if recent.exists():
        AlertCheck.objects.filter(id=alert_check.id).update(investigation_status=InvestigationStatus.SKIPPED)
        return False
    AlertCheck.objects.filter(id=alert_check.id).update(investigation_status=InvestigationStatus.PENDING)
    return True
