"""Safety-net dispatcher for investigation-gated alert notifications.

When an alert has `investigation_gates_notifications=True`, the synchronous
notification in `notify_alert` is skipped and the investigation workflow
becomes responsible for firing it. That's great when the workflow completes —
but if Temporal has a hiccup, the workflow times out, or any other path leaves
an AlertCheck with no `notification_sent_at` and no `notification_suppressed_by_agent`,
the user could silently miss a real fire.

`run_investigation_notification_safety_net` is invoked on a Temporal schedule
(see `posthog/temporal/alerts/schedule.py`), looks for gated checks past a grace
period, and force-dispatches the notification with whatever context we have on
hand. Terminal investigation statuses (DONE/FAILED) get picked up after
`INVESTIGATION_NOTIFY_GRACE_MINUTES`; non-terminal statuses wait the longer
`INVESTIGATION_RUNNING_GRACE_MINUTES` so we never preempt a healthy long run.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

import structlog

from posthog.schema import AlertState

from posthog.models.alert import AlertCheck, InvestigationStatus
from posthog.tasks.alerts.utils import dispatch_alert_notification, record_alert_delivery

logger = structlog.get_logger(__name__)


# Fast pickup for investigations that already reached a terminal state — the workflow
# is no longer going to dispatch, so we shouldn't make the user wait.
INVESTIGATION_NOTIFY_GRACE_MINUTES = 5

# Fallback for non-terminal investigations (RUNNING / PENDING / SKIPPED / null). Must
# exceed the activity's worst case — `ANOMALY_INVESTIGATION_ACTIVITY_START_TO_CLOSE`
# (20 min) × `ANOMALY_INVESTIGATION_ACTIVITY_MAX_ATTEMPTS` (2) — so a healthy long
# investigation isn't preempted by a duplicate force-dispatch.
INVESTIGATION_RUNNING_GRACE_MINUTES = 45


def run_investigation_notification_safety_net() -> int:
    """Dispatch notifications for gated AlertChecks whose investigation stalled.

    Returns the number of checks that were force-notified (for metrics / tests).
    """
    now = datetime.now(UTC)
    terminal_cutoff = now - timedelta(minutes=INVESTIGATION_NOTIFY_GRACE_MINUTES)
    running_cutoff = now - timedelta(minutes=INVESTIGATION_RUNNING_GRACE_MINUTES)
    # Scope the sweep to alerts that opted into the investigation agent rather
    # than the narrower `investigation_gates_notifications` flag. The latter is
    # a sub-toggle a user might flip off mid-investigation, which would hide a
    # legitimately-held check from this safety net; `investigation_agent_enabled`
    # is a stickier configuration knob and picks up exactly the checks whose
    # dispatch could have been the workflow's responsibility.
    candidates = (
        AlertCheck.objects.select_related("alert_configuration")
        .filter(
            state=AlertState.FIRING,
            notification_sent_at__isnull=True,
            notification_suppressed_by_agent=False,
            # Pre-PR-3 `notify_alert` populated `targets_notified` without setting
            # `notification_sent_at`. New code writes both atomically, so the combination
            # (targets_notified populated, notification_sent_at NULL) only occurs in
            # legacy data delivered before this safety net existed; skip it.
            targets_notified={},
            alert_configuration__investigation_agent_enabled=True,
        )
        .filter(
            # Terminal investigation states (DONE / FAILED): the workflow is not coming
            # back, so a 5-min grace gets stuck dispatches through quickly. Non-terminal
            # states (RUNNING / PENDING / SKIPPED / null): wait past the activity's
            # full retry budget so we don't race a healthy long-running investigation.
            Q(
                investigation_status__in=[InvestigationStatus.DONE, InvestigationStatus.FAILED],
                created_at__lte=terminal_cutoff,
            )
            | Q(created_at__lte=running_cutoff)
        )
    )

    notified = 0
    for check in candidates.iterator():
        alert = check.alert_configuration
        if alert is None or not alert.enabled:
            continue

        try:
            with transaction.atomic():
                locked = AlertCheck.objects.select_for_update().get(id=check.id)
                if locked.notification_sent_at is not None or locked.notification_suppressed_by_agent:
                    continue
                breaches = _fallback_breach_descriptions(locked)
                targets = dispatch_alert_notification(alert, locked, breaches)
                if targets is not None:
                    record_alert_delivery(alert, locked, targets)
                # Set notification_sent_at in lock-step with record_alert_delivery so
                # gating/idempotency reads that still use this marker stay consistent.
                locked.notification_sent_at = timezone.now()
                locked.save(update_fields=["notification_sent_at"])
        except Exception:
            logger.exception(
                "alert.investigation_safety_net_failed",
                alert_id=str(alert.id),
                alert_check_id=str(check.id),
            )
            continue

        logger.warning(
            "alert.investigation_safety_net_dispatched",
            alert_id=str(alert.id),
            alert_check_id=str(check.id),
            investigation_status=check.investigation_status,
        )
        notified += 1

    return notified


def _fallback_breach_descriptions(alert_check: AlertCheck) -> list[str]:
    """Minimal breach description for a safety-net dispatch (no verdict yet)."""
    triggered_dates = alert_check.triggered_dates or []
    if triggered_dates:
        if len(triggered_dates) == 1:
            head = f"Anomaly detected on {triggered_dates[0]}."
        else:
            head = f"Anomaly detected from {triggered_dates[0]} to {triggered_dates[-1]}."
    elif alert_check.calculated_value is not None:
        head = f"Calculated value at fire: {alert_check.calculated_value}."
    else:
        head = "Anomaly detected."
    return [head, "(Investigation agent did not complete before the notification grace period expired.)"]
