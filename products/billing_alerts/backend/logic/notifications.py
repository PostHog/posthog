from __future__ import annotations

from datetime import datetime

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.alerting.destinations import find_alert_destination_hog_functions, produce_alert_internal_event
from posthog.exceptions_capture import capture_exception

from products.billing_alerts.backend.alert_destinations import (
    BILLING_ALERT_DESTINATION_IDS_PROPERTY,
    EVENT_KIND_CONFIG,
    EventKind,
)
from products.billing_alerts.backend.models import BillingAlertConfiguration, BillingAlertEvent
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

logger = structlog.get_logger(__name__)


def _kind_for_event(event: BillingAlertEvent) -> EventKind | None:
    if event.kind == BillingAlertEvent.Kind.BROKEN_CONFIG:
        return "broken"
    if event.kind == BillingAlertEvent.Kind.FIRING:
        return "firing"
    if event.kind == BillingAlertEvent.Kind.RESOLVED:
        return "resolved"
    if event.kind == BillingAlertEvent.Kind.ERRORED:
        return "errored"
    return None


def _properties(event: BillingAlertEvent, now: datetime, destination_ids: list[str]) -> dict:
    alert = event.alert
    return {
        "alert_id": str(alert.id),
        "alert_name": alert.name,
        BILLING_ALERT_DESTINATION_IDS_PROPERTY: destination_ids,
        "metric": event.metric,
        "threshold_type": alert.threshold_type,
        "threshold_percentage": str(event.threshold_percentage_snapshot)
        if event.threshold_percentage_snapshot is not None
        else None,
        "threshold_value": str(event.threshold_value_snapshot) if event.threshold_value_snapshot is not None else None,
        "minimum_value": str(event.minimum_value_snapshot) if event.minimum_value_snapshot is not None else None,
        "current_value": str(event.current_value) if event.current_value is not None else None,
        "baseline_value": str(event.baseline_value) if event.baseline_value is not None else None,
        "absolute_delta": str(event.absolute_delta) if event.absolute_delta is not None else None,
        "relative_delta_percentage": str(event.relative_delta_percentage)
        if event.relative_delta_percentage is not None
        else None,
        "evaluation_date": event.evaluation_date.isoformat() if event.evaluation_date else None,
        "reason": event.reason,
        "error_message": event.error_message,
        "consecutive_failures": alert.consecutive_failures,
        "triggered_at": now.isoformat(),
    }


def _destination_hog_functions(event: BillingAlertEvent) -> list[HogFunction]:
    alert = event.alert
    kind = _kind_for_event(event)
    if kind is None:
        return []
    return find_alert_destination_hog_functions(
        team_id=alert.execution_team_id,
        alert_id=str(alert.id),
        event_id=EVENT_KIND_CONFIG[kind].event_id,
    )


def _produce_billing_alert_internal_event(
    *,
    event_id: str,
    alert_id: str,
    event_name: str,
    team_id: int,
    properties: dict,
    notification_sent_at: datetime,
) -> None:
    try:
        produce_alert_internal_event(
            team_id=team_id,
            event_name=event_name,
            properties=properties,
            uuid=event_id,
        )
    except Exception as e:
        BillingAlertEvent.objects.filter(id=event_id, notification_sent_at=notification_sent_at).update(
            notification_sent_at=None,
            targets_notified={},
        )
        BillingAlertConfiguration.objects.filter(id=alert_id, last_notified_at=notification_sent_at).update(
            last_notified_at=None
        )
        capture_exception(e, {"event_id": event_id, "feature": "billing_alerts"})
        logger.exception(
            "Failed to emit billing alert internal event",
            event_id=event_id,
            event_name=event_name,
        )
        raise


def dispatch_billing_alert_event(event: BillingAlertEvent, now: datetime | None = None) -> int:
    now = now or timezone.now()
    with transaction.atomic():
        locked_event = BillingAlertEvent.objects.select_for_update().select_related("alert").get(id=event.id)
        if locked_event.targets_notified or locked_event.notification_sent_at is not None:
            return 0

        kind = _kind_for_event(locked_event)
        if kind is None:
            return 0
        event_name = EVENT_KIND_CONFIG[kind].event_id

        destinations = _destination_hog_functions(locked_event)
        if not destinations:
            return 0

        destination_ids = [str(destination.id) for destination in destinations]
        event_id = str(locked_event.id)
        alert_id = str(locked_event.alert_id)
        team_id = locked_event.alert.execution_team_id
        properties = _properties(locked_event, now, destination_ids)

        locked_event.notification_sent_at = now
        locked_event.targets_notified = {"hog_functions": destination_ids}
        locked_event.save(update_fields=["notification_sent_at", "targets_notified"])
        locked_event.alert.last_notified_at = now
        locked_event.alert.save(update_fields=["last_notified_at", "updated_at"])

        transaction.on_commit(
            lambda: _produce_billing_alert_internal_event(
                event_id=event_id,
                alert_id=alert_id,
                event_name=event_name,
                team_id=team_id,
                properties=properties,
                notification_sent_at=now,
            )
        )

    return len(destinations)
