"""Safety-net dispatcher for investigation-gated alert notifications.

When an alert has `investigation_gates_notifications=True`, the synchronous
notification in `check_alert_and_notify_atomically` is skipped and the
investigation workflow becomes responsible for firing it. That's great when
the workflow completes — but if Temporal has a hiccup, the workflow times out,
or any other path leaves an AlertCheck with no `notification_sent_at` and no
`notification_suppressed_by_agent`, the user could silently miss a real fire.

This task runs on a Celery beat schedule, looks for gated checks that have
been pending past a grace period, and force-dispatches the notification with
whatever context we have on hand. After `INVESTIGATION_NOTIFY_GRACE_MINUTES`
we assume the investigation is not coming back.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.schema import AlertState

from posthog.models.alert import AlertCheck, InvestigationStatus
from posthog.tasks.alerts.utils import send_notifications_for_breaches

logger = structlog.get_logger(__name__)


INVESTIGATION_NOTIFY_GRACE_MINUTES = 5


def run_investigation_notification_safety_net() -> int:
    """Dispatch notifications for gated AlertChecks whose investigation stalled.

    Returns the number of checks that were force-notified (for metrics / tests).
    """
    cutoff = datetime.now(UTC) - timedelta(minutes=INVESTIGATION_NOTIFY_GRACE_MINUTES)
    candidates = (
        AlertCheck.objects.select_related("alert_configuration")
        .filter(
            state=AlertState.FIRING,
            notification_sent_at__isnull=True,
            notification_suppressed_by_agent=False,
            created_at__lte=cutoff,
            alert_configuration__investigation_gates_notifications=True,
        )
        .exclude(investigation_status=InvestigationStatus.DONE)
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
                send_notifications_for_breaches(alert, breaches)
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
