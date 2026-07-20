from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from django.utils import timezone

from posthog.kafka_client.client import ProduceResult

from products.alerts.backend.destinations import (
    alert_internal_event_delivered,
    flush_alert_internal_events,
    produce_alert_internal_event,
)
from products.billing_alerts.backend.alert_destinations import (
    BILLING_ALERT_EVENT_IDS,
    DESTINATION_TYPE_BY_TEMPLATE_ID,
    EVENT_KIND_CONFIG,
    EventKind,
)
from products.billing_alerts.backend.logic.state_machine import (
    BillingAlertAlreadyEvaluated,
    BillingAlertCheck,
    commit_billing_alert_check,
    prepare_billing_alert_check,
    prepare_billing_alert_failure,
)
from products.billing_alerts.backend.models import BillingAlertConfiguration, BillingAlertEvent
from products.cdp.backend.models.hog_functions.hog_function import HogFunction

NOTIFICATION_FLUSH_TIMEOUT_SECONDS = 10


@dataclass(frozen=True)
class PendingBillingAlertDispatch:
    check: BillingAlertCheck
    event_name: str | None
    destination_ids: list[str]
    produce_result: ProduceResult | None


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
    rows = HogFunction.objects.filter(
        team_id=event.alert.execution_team_id,
        enabled=True,
        deleted=False,
        template_id__in=list(DESTINATION_TYPE_BY_TEMPLATE_ID),
        filters__properties__contains=[{"key": "alert_id", "value": str(event.alert_id)}],
    ).values_list("id", "template_id", "filters")
    ids_by_template_and_event: dict[str, dict[str, str]] = {}
    for destination_id, template_id, filters in rows:
        if template_id is None or not isinstance(filters, dict):
            continue
        configured_events = filters.get("events") or []
        if not isinstance(configured_events, list):
            continue
        configured_event_id = next(
            (
                configured_event.get("id")
                for configured_event in configured_events
                if isinstance(configured_event, dict) and configured_event.get("type") == "events"
            ),
            None,
        )
        if configured_event_id in BILLING_ALERT_EVENT_IDS:
            ids_by_template_and_event.setdefault(template_id, {})[configured_event_id] = str(destination_id)

    required_events = set(BILLING_ALERT_EVENT_IDS)
    return sorted(
        event_ids[event_id] for event_ids in ids_by_template_and_event.values() if set(event_ids) == required_events
    )


def _enqueue(check: BillingAlertCheck) -> PendingBillingAlertDispatch:
    event = check.event
    kind = _kind_for_event(event)
    if kind is None:
        return PendingBillingAlertDispatch(
            check=check,
            event_name=None,
            destination_ids=[],
            produce_result=None,
        )

    event_name = EVENT_KIND_CONFIG[kind].event_id
    destination_ids = _destination_ids(event)
    produce_result = None
    if destination_ids:
        produce_result = produce_alert_internal_event(
            team_id=event.alert.execution_team_id,
            event_name=event_name,
            properties=_properties(event, check.now, consecutive_failures=check.outcome.consecutive_failures),
            timestamp=check.now,
            uuid=str(check.claim.delivery_uuid),
        )
    return PendingBillingAlertDispatch(
        check=check,
        event_name=event_name,
        destination_ids=destination_ids,
        produce_result=produce_result,
    )


def prepare_billing_alert_dispatch(
    alert: BillingAlertConfiguration,
    *,
    now: datetime | None = None,
    billing_response: dict | None = None,
    query_duration_ms: int | None = None,
    error: Exception | None = None,
    is_transient_error: bool = False,
    failure_reason: str = "Billing alert evaluation failed.",
    source: str = BillingAlertEvent.Source.SCHEDULED,
) -> PendingBillingAlertDispatch:
    """Evaluate an alert and enqueue any internal event without persisting the outcome."""
    now = now or timezone.now()
    if error is None:
        check = prepare_billing_alert_check(
            alert,
            source=source,
            now=now,
            billing_response=billing_response,
            query_duration_ms=query_duration_ms,
        )
    else:
        check = prepare_billing_alert_failure(
            alert,
            error,
            source=source,
            now=now,
            query_duration_ms=query_duration_ms,
            is_transient_error=is_transient_error,
            reason=failure_reason,
        )
    if _kind_for_event(check.event) is not None:
        return _enqueue(check)
    return PendingBillingAlertDispatch(
        check=check,
        event_name=None,
        destination_ids=[],
        produce_result=None,
    )


def flush_pending_billing_alert_dispatches(dispatches: list[PendingBillingAlertDispatch]) -> None:
    """Flush one activity batch after all internal events have been produced."""
    if any(dispatch.produce_result is not None for dispatch in dispatches):
        flush_alert_internal_events(NOTIFICATION_FLUSH_TIMEOUT_SECONDS)


def commit_pending_billing_alert_dispatch(
    dispatch: PendingBillingAlertDispatch,
) -> tuple[BillingAlertEvent, int]:
    """Resolve producer acknowledgement, then persist the corresponding lifecycle outcome."""
    delivered = dispatch.event_name is None
    if dispatch.event_name is not None and dispatch.produce_result is not None:
        delivered = alert_internal_event_delivered(
            dispatch.produce_result,
            team_id=dispatch.check.event.alert.execution_team_id,
            alert_id=str(dispatch.check.event.alert_id),
            event_name=dispatch.event_name,
        )

    event = commit_billing_alert_check(
        dispatch.check,
        notification_delivered=delivered,
        destination_ids=dispatch.destination_ids,
    )
    return event, len(dispatch.destination_ids) if delivered else 0


def evaluate_and_dispatch_billing_alert(
    alert: BillingAlertConfiguration,
    *,
    now: datetime | None = None,
    billing_response: dict | None = None,
    query_duration_ms: int | None = None,
    error: Exception | None = None,
    is_transient_error: bool = False,
    failure_reason: str = "Billing alert evaluation failed.",
    source: str = BillingAlertEvent.Source.MANUAL,
) -> tuple[BillingAlertEvent, int]:
    """Evaluate, cross the shared delivery barrier, then persist the safe outcome."""
    try:
        dispatch = prepare_billing_alert_dispatch(
            alert,
            now=now,
            billing_response=billing_response,
            query_duration_ms=query_duration_ms,
            error=error,
            is_transient_error=is_transient_error,
            failure_reason=failure_reason,
            source=source,
        )
    except BillingAlertAlreadyEvaluated as already_evaluated:
        if already_evaluated.event is None:
            raise
        return already_evaluated.event, 0
    flush_pending_billing_alert_dispatches([dispatch])
    return commit_pending_billing_alert_dispatch(dispatch)
