from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from products.alerts.backend.destinations import (
    alert_internal_event_delivered,
    flush_alert_internal_events,
    produce_alert_internal_event,
)
from products.billing_alerts.backend.alert_destinations import (
    DESTINATION_TYPE_BY_TEMPLATE_ID,
    EVENT_KIND_CONFIG,
    EventKind,
)
from products.billing_alerts.backend.logic.state_machine import (
    BillingAlertCheck,
    commit_billing_alert_check,
    event_should_dispatch,
    prepare_billing_alert_check,
    prepare_billing_alert_failure,
)
from products.billing_alerts.backend.models import BillingAlertConfiguration, BillingAlertEvent
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

NOTIFICATION_FLUSH_TIMEOUT_SECONDS = 10


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


def _properties(event: BillingAlertEvent, now: datetime, *, consecutive_failures: int) -> dict:
    alert = event.alert
    return {
        "alert_id": str(alert.id),
        "alert_name": alert.name,
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
        "consecutive_failures": consecutive_failures,
        "triggered_at": now.isoformat(),
    }


def _destination_ids(event: BillingAlertEvent) -> list[str]:
    kind = _kind_for_event(event)
    if kind is None:
        return []
    event_id = EVENT_KIND_CONFIG[kind].event_id
    return [
        str(destination_id)
        for destination_id in HogFunction.objects.filter(
            team_id=event.alert.execution_team_id,
            deleted=False,
            template_id__in=list(DESTINATION_TYPE_BY_TEMPLATE_ID),
            filters__events__contains=[{"id": event_id, "type": "events"}],
            filters__properties__contains=[{"key": "alert_id", "value": str(event.alert_id)}],
        ).values_list("id", flat=True)
    ]


def _deliver(check: BillingAlertCheck) -> tuple[bool, list[str]]:
    event = check.event
    kind = _kind_for_event(event)
    if kind is None:
        return True, []

    event_name = EVENT_KIND_CONFIG[kind].event_id
    destination_ids = _destination_ids(event)
    produce_result = produce_alert_internal_event(
        team_id=event.alert.execution_team_id,
        event_name=event_name,
        properties=_properties(event, check.now, consecutive_failures=check.outcome.consecutive_failures),
        timestamp=check.now,
        uuid=str(event.id),
    )
    if produce_result is None:
        return False, destination_ids

    flush_alert_internal_events(NOTIFICATION_FLUSH_TIMEOUT_SECONDS)
    delivered = alert_internal_event_delivered(
        produce_result,
        team_id=event.alert.execution_team_id,
        alert_id=str(event.alert_id),
        event_name=event_name,
    )
    return delivered, destination_ids


def evaluate_and_dispatch_billing_alert(
    alert: BillingAlertConfiguration,
    *,
    now: datetime | None = None,
    billing_response: dict | None = None,
    query_duration_ms: int | None = None,
    error: Exception | None = None,
    is_transient_error: bool = False,
    failure_reason: str = "Billing alert evaluation failed.",
) -> tuple[BillingAlertEvent, int]:
    """Evaluate, cross the shared delivery barrier, then persist the safe outcome."""
    now = now or timezone.now()

    def prepare(current_alert: BillingAlertConfiguration) -> BillingAlertCheck:
        if error is None:
            return prepare_billing_alert_check(
                current_alert,
                now=now,
                billing_response=billing_response,
                query_duration_ms=query_duration_ms,
            )
        return prepare_billing_alert_failure(
            current_alert,
            error,
            now=now,
            query_duration_ms=query_duration_ms,
            is_transient_error=is_transient_error,
            reason=failure_reason,
        )

    check = prepare(alert)
    with transaction.atomic():
        locked_alert = BillingAlertConfiguration.objects.select_for_update().get(pk=alert.pk)
        if locked_alert.updated_at != check.configuration_updated_at:
            check = prepare(locked_alert)
        else:
            check = replace(check, alert=locked_alert)
            check.event.alert = locked_alert
            check.event.team_id = locked_alert.team_id

        delivered, destination_ids = _deliver(check) if event_should_dispatch(check.event) else (True, [])
        event = commit_billing_alert_check(
            check,
            notification_delivered=delivered,
            destination_ids=destination_ids,
        )
        return event, len(destination_ids) if delivered else 0


def dispatch_billing_alert_event(event: BillingAlertEvent, now: datetime | None = None) -> int:
    """Compatibility path for an event persisted by an older in-flight Temporal activity."""
    now = now or timezone.now()
    with transaction.atomic():
        locked_event = BillingAlertEvent.objects.select_for_update().select_related("alert").get(id=event.id)
        if locked_event.targets_notified or locked_event.notification_sent_at is not None:
            return 0

        # This path only serves old in-flight workflow histories. Keep the row lock
        # through delivery so concurrent retries cannot enqueue the same event twice.
        kind = _kind_for_event(locked_event)
        if kind is None:
            return 0
        destination_ids = _destination_ids(locked_event)
        event_name = EVENT_KIND_CONFIG[kind].event_id
        produce_result = produce_alert_internal_event(
            team_id=locked_event.alert.execution_team_id,
            event_name=event_name,
            properties=_properties(locked_event, now, consecutive_failures=locked_event.alert.consecutive_failures),
            timestamp=now,
            uuid=str(locked_event.id),
        )
        if produce_result is None:
            return 0
        flush_alert_internal_events(NOTIFICATION_FLUSH_TIMEOUT_SECONDS)
        if not alert_internal_event_delivered(
            produce_result,
            team_id=locked_event.alert.execution_team_id,
            alert_id=str(locked_event.alert_id),
            event_name=event_name,
        ):
            return 0

        locked_event.notification_sent_at = now
        locked_event.targets_notified = {"hog_functions": destination_ids}
        locked_event.save(update_fields=["notification_sent_at", "targets_notified"])
        locked_event.alert.last_notified_at = now
        locked_event.alert.save(update_fields=["last_notified_at", "updated_at"])
    return len(destination_ids)
