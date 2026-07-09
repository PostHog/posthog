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

INVESTIGATION_COOLDOWN = timedelta(hours=1)
INVESTIGATION_BACKOFF_CAP = timedelta(hours=24)

_ACTIVE_INVESTIGATION_STATUSES = [
    InvestigationStatus.PENDING,
    InvestigationStatus.RUNNING,
]


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
    if new_state != AlertState.FIRING:
        return False
    if alert.investigation_mode == AlertConfiguration.InvestigationMode.POSTHOG_CODE:
        if previous_state != AlertState.FIRING:
            return True
        return bool(alert.investigation_rerun_on_continued_breach)
    # notebook mode: detector alerts only, transition into FIRING only
    if not alert.detector_config:
        return False
    return previous_state != AlertState.FIRING


def get_episode_start(alert: AlertConfiguration) -> datetime | None:
    """Return the created_at of the most recent AlertCheck with state != FIRING (episode boundary).

    Returns None when there is no such check (the alert has been firing since its first check).
    """
    return (
        AlertCheck.objects.filter(alert_configuration=alert)
        .exclude(state=AlertState.FIRING)
        .order_by("-created_at")
        .values_list("created_at", flat=True)
        .first()
    )


def _posthog_code_effective_cooldown(alert: AlertConfiguration) -> timedelta:
    """Compute the exponential backoff cooldown for the current firing episode.

    Episode start is the created_at of the most recent AlertCheck with state != FIRING.
    Completed = DONE+FAILED investigation checks after that boundary.
    Cooldown = 1h * 2**min(completed, 5), capped at 24h.
    """
    episode_start = get_episode_start(alert)
    completed = AlertCheck.objects.filter(
        alert_configuration=alert,
        investigation_status__in=[
            InvestigationStatus.DONE,
            InvestigationStatus.FAILED,
        ],
    )
    if episode_start is not None:
        completed = completed.filter(created_at__gt=episode_start)
    exponent = min(completed.count(), 5)
    return min(INVESTIGATION_COOLDOWN * (2**exponent), INVESTIGATION_BACKOFF_CAP)


def claim_investigation_slot(alert: AlertConfiguration, alert_check: AlertCheck) -> bool:
    """Try to claim the cooldown slot for `alert` and return True on success.

    On success, marks `alert_check.investigation_status = PENDING`. On failure
    (a recent investigation is RUNNING/DONE/PENDING within the cooldown window),
    marks it SKIPPED and returns False so flappy alerts don't pile up.

    Caller must run this inside a transaction so the read-then-write is atomic.

    In posthog_code mode:
    - FAILED checks also occupy the slot (unlike notebook mode, where FAILED is ignored).
    - The effective cooldown grows exponentially with the number of completed investigations
      in the current firing episode (see `_posthog_code_effective_cooldown`).
    - Active checks (PENDING/RUNNING) always block regardless of window age.

    In notebook mode:
    - FAILED checks do not occupy the slot.
    - Active checks (PENDING/RUNNING) block only within the 1h cooldown window.
    - The original window-bounded behavior is preserved byte-for-byte.
    """
    is_posthog_code = alert.investigation_mode == AlertConfiguration.InvestigationMode.POSTHOG_CODE

    if is_posthog_code:
        # In posthog_code mode, active statuses always block — no window check needed.
        active_blocking = (
            AlertCheck.objects.filter(
                alert_configuration=alert,
                investigation_status__in=_ACTIVE_INVESTIGATION_STATUSES,
            )
            .exclude(id=alert_check.id)
            .exists()
        )
        if active_blocking:
            AlertCheck.objects.filter(id=alert_check.id).update(investigation_status=InvestigationStatus.SKIPPED)
            return False

        # Completed statuses block within the exponential-backoff cooldown window.
        # PENDING/RUNNING are already handled above, so only check DONE and FAILED here.
        cooldown = _posthog_code_effective_cooldown(alert)
        window_start = datetime.now(UTC) - cooldown
        recent_blocking = (
            AlertCheck.objects.filter(
                alert_configuration=alert,
                investigation_status__in=[InvestigationStatus.DONE, InvestigationStatus.FAILED],
                created_at__gte=window_start,
            )
            .exclude(id=alert_check.id)
            .exists()
        )
    else:
        # Notebook mode: all occupying statuses (PENDING, RUNNING, DONE) are window-bounded.
        window_start = datetime.now(UTC) - INVESTIGATION_COOLDOWN
        recent_blocking = (
            AlertCheck.objects.filter(
                alert_configuration=alert,
                investigation_status__in=[
                    InvestigationStatus.PENDING,
                    InvestigationStatus.RUNNING,
                    InvestigationStatus.DONE,
                ],
                created_at__gte=window_start,
            )
            .exclude(id=alert_check.id)
            .exists()
        )

    if recent_blocking:
        AlertCheck.objects.filter(id=alert_check.id).update(investigation_status=InvestigationStatus.SKIPPED)
        return False
    AlertCheck.objects.filter(id=alert_check.id).update(investigation_status=InvestigationStatus.PENDING)
    return True
