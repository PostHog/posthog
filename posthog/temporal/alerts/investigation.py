"""Investigation-agent trigger helpers used by the Temporal evaluate_alert activity.

The trigger and notification-gating decisions both run inside `evaluate_alert`
in the same DB transaction as the AlertCheck insert, so the read-then-write that
claims the cooldown lease stays consistent. This module exposes the primitives
as pure functions so they can be unit-tested independently of Temporal.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from posthog.schema import AlertState

from posthog.models import AlertConfiguration
from posthog.models.alert import AlertCheck, InvestigationStatus

INVESTIGATION_COOLDOWN = timedelta(hours=1)


def should_trigger_investigation(
    alert: AlertConfiguration,
    *,
    previous_state: str | None,
    new_state: str,
) -> bool:
    """True when this fire is eligible for an investigation, ignoring cooldown.

    Cooldown is enforced by `claim_investigation_slot`, which does the read-then-write
    inside the caller's transaction.
    """
    if not alert.investigation_agent_enabled:
        return False
    if not alert.detector_config:
        return False
    if previous_state == AlertState.FIRING:
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
    cooldown_since = datetime.now(UTC) - INVESTIGATION_COOLDOWN
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
