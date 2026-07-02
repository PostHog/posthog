from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from django.db.models import F

import structlog
import temporalio.activity

from posthog.alerting.scheduling import due_alerts_q
from posthog.exceptions_capture import capture_exception
from posthog.models import Organization
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater

from products.billing_alerts.backend.logic.evaluator import fetch_billing_data
from products.billing_alerts.backend.logic.notifications import dispatch_billing_alert_event
from products.billing_alerts.backend.logic.state_machine import (
    evaluate_and_record_billing_alert,
    event_should_dispatch,
    record_billing_alert_failure,
)
from products.billing_alerts.backend.models import BillingAlertConfiguration, BillingAlertEvent
from products.billing_alerts.backend.temporal.types import (
    BillingAlertInfo,
    EvaluateBillingAlertBatchActivityInputs,
    NotifyBillingAlertEventsActivityInputs,
)

BILLING_ALERT_BATCH_SIZE = 50
MAX_DUE_BILLING_ALERTS_PER_TICK = 500
logger = structlog.get_logger(__name__)


def _group_key(alert: BillingAlertConfiguration) -> tuple[Any, ...]:
    return (
        str(alert.organization_id),
        alert.metric,
        alert.baseline_window_days,
        alert.evaluation_delay_hours,
    )


def _record_group_failure(
    alert_group: list[BillingAlertConfiguration],
    error: Exception,
    *,
    now: datetime,
    is_transient_error: bool,
    reason: str,
) -> list[str]:
    first_alert = alert_group[0]
    alert_ids = [str(alert.id) for alert in alert_group]
    capture_exception(error, {"alert_ids": alert_ids, "feature": "billing_alerts"})
    logger.exception(
        "Billing alert group failure",
        alert_ids=alert_ids,
        organization_id=str(first_alert.organization_id),
        reason=reason,
    )

    dispatch_event_ids: list[str] = []
    for alert in alert_group:
        event = record_billing_alert_failure(
            alert,
            error,
            now=now,
            is_transient_error=is_transient_error,
            reason=reason,
        )
        if event_should_dispatch(event):
            dispatch_event_ids.append(str(event.id))
    return dispatch_event_ids


def _evaluate_billing_alerts(inputs: EvaluateBillingAlertBatchActivityInputs) -> list[str]:
    now = datetime.now(UTC)
    alerts = list(
        BillingAlertConfiguration.objects.filter(id__in=inputs.alert_ids, enabled=True)
        .exclude(state=BillingAlertConfiguration.State.BROKEN)
        .order_by("organization_id", "metric", "id")
    )
    grouped: dict[tuple[Any, ...], list[BillingAlertConfiguration]] = defaultdict(list)
    for alert in alerts:
        grouped[_group_key(alert)].append(alert)

    dispatch_event_ids: list[str] = []
    for alert_group in grouped.values():
        first_alert = alert_group[0]
        try:
            organization = Organization.objects.get(id=first_alert.organization_id)
        except Organization.DoesNotExist as e:
            dispatch_event_ids.extend(
                _record_group_failure(
                    alert_group,
                    e,
                    now=now,
                    is_transient_error=False,
                    reason="Billing alert organization was not found.",
                )
            )
            continue

        try:
            billing_response, query_duration_ms = fetch_billing_data(first_alert, organization, now=now)
        except Exception as e:
            dispatch_event_ids.extend(
                _record_group_failure(
                    alert_group,
                    e,
                    now=now,
                    is_transient_error=True,
                    reason="Billing alert data fetch failed.",
                )
            )
            continue

        for alert in alert_group:
            event = evaluate_and_record_billing_alert(
                alert,
                now=now,
                billing_response=billing_response,
                query_duration_ms=query_duration_ms,
            )
            if event_should_dispatch(event):
                dispatch_event_ids.append(str(event.id))
    return dispatch_event_ids


@temporalio.activity.defn
async def discover_due_billing_alerts_activity() -> list[BillingAlertInfo]:
    @database_sync_to_async(thread_sensitive=False)
    def get_due_alerts() -> list[BillingAlertInfo]:
        now = datetime.now(UTC)
        alerts = (
            BillingAlertConfiguration.objects.filter(
                due_alerts_q(now, broken_state=BillingAlertConfiguration.State.BROKEN)
            )
            .order_by(F("next_check_at").asc(nulls_first=True))
            .values_list("id", flat=True)[:MAX_DUE_BILLING_ALERTS_PER_TICK]
        )
        return [BillingAlertInfo(alert_id=str(alert_id)) for alert_id in alerts]

    async with Heartbeater():
        return await get_due_alerts()


@temporalio.activity.defn
async def evaluate_billing_alert_batch_activity(inputs: EvaluateBillingAlertBatchActivityInputs) -> list[str]:
    async with Heartbeater():
        return await database_sync_to_async(_evaluate_billing_alerts, thread_sensitive=False)(inputs)


@temporalio.activity.defn
async def notify_billing_alert_events_activity(inputs: NotifyBillingAlertEventsActivityInputs) -> int:
    @database_sync_to_async(thread_sensitive=False)
    def notify_events() -> int:
        dispatched = 0
        for event in BillingAlertEvent.objects.filter(id__in=inputs.event_ids).select_related("alert"):
            dispatched += dispatch_billing_alert_event(event)
        return dispatched

    async with Heartbeater():
        return await notify_events()
