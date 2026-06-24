from __future__ import annotations

from datetime import datetime

from django.db import transaction
from django.utils import timezone

import structlog

from posthog.cdp.internal_events import InternalEventEvent, produce_internal_event
from posthog.exceptions_capture import capture_exception

from products.billing_alerts.backend.alert_destinations import (
    BILLING_ALERT_DESTINATION_IDS_PROPERTY,
    DESTINATION_TYPE_BY_TEMPLATE_ID,
    EVENT_KIND_CONFIG,
)
from products.billing_alerts.backend.models import BillingAlertDelivery, BillingAlertEvent
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

logger = structlog.get_logger(__name__)


def _kind_for_event(event: BillingAlertEvent) -> str | None:
    if event.kind == BillingAlertEvent.Kind.BROKEN_CONFIG:
        return "broken"
    if event.kind in (BillingAlertEvent.Kind.FIRING, BillingAlertEvent.Kind.RESOLVED, BillingAlertEvent.Kind.ERRORED):
        return event.kind
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
    event_id = EVENT_KIND_CONFIG[kind].event_id
    return list(
        HogFunction.objects.filter(
            team_id=alert.execution_team_id,
            deleted=False,
            template_id__in=list(DESTINATION_TYPE_BY_TEMPLATE_ID),
            filters__events__contains=[{"id": event_id, "type": "events"}],
            filters__properties__contains=[{"key": "alert_id", "value": str(alert.id)}],
        ).only("id", "template_id")
    )


def dispatch_billing_alert_event(event: BillingAlertEvent, now: datetime | None = None) -> int:
    now = now or timezone.now()
    with transaction.atomic():
        locked_event = BillingAlertEvent.objects.select_for_update().select_related("alert").get(id=event.id)
        if locked_event.notification_sent_at is not None:
            return 0

        kind = _kind_for_event(locked_event)
        if kind is None:
            return 0
        event_name = EVENT_KIND_CONFIG[kind].event_id

        destinations = _destination_hog_functions(locked_event)
        if not destinations:
            return 0

        destination_ids = [str(destination.id) for destination in destinations]
        for destination in destinations:
            destination_type = DESTINATION_TYPE_BY_TEMPLATE_ID.get(destination.template_id)
            if destination_type is None:
                continue
            BillingAlertDelivery.objects.get_or_create(
                event=locked_event,
                destination_type=destination_type,
                destination_key=str(destination.id),
                defaults={
                    "hog_function_id": destination.id,
                    "idempotency_key": f"billing-alert-{locked_event.id}-{destination.id}",
                    "status": BillingAlertDelivery.Status.QUEUED,
                },
            )

        locked_event.notification_sent_at = now
        locked_event.save(update_fields=["notification_sent_at"])
        locked_event.alert.last_notified_at = now
        locked_event.alert.save(update_fields=["last_notified_at", "updated_at"])

        try:
            produce_internal_event(
                team_id=locked_event.alert.execution_team_id,
                event=InternalEventEvent(
                    event=event_name,
                    distinct_id=f"team_{locked_event.alert.execution_team_id}",
                    properties=_properties(locked_event, now, destination_ids),
                    uuid=str(locked_event.id),
                ),
            )
        except Exception as e:
            capture_exception(e, {"event_id": str(locked_event.id), "feature": "billing_alerts"})
            logger.exception(
                "Failed to emit billing alert internal event",
                event_id=str(locked_event.id),
                event_name=event_name,
            )
            raise

    return len(destinations)
