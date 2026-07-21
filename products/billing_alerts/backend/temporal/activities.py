from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from django.db.models import F, Q, QuerySet, Window
from django.db.models.functions import RowNumber

import structlog
import temporalio.activity

from posthog.exceptions_capture import capture_exception
from posthog.models import Organization
from posthog.sync import database_sync_to_async
from posthog.temporal.common.heartbeat import Heartbeater

from products.billing_alerts.backend.logic.evaluator import expected_evaluation_date, fetch_billing_data
from products.billing_alerts.backend.logic.notifications import (
    PendingBillingAlertDispatch,
    commit_pending_billing_alert_dispatches,
    prepare_billing_alert_dispatch,
)
from products.billing_alerts.backend.logic.state_machine import (
    BillingAlertAlreadyEvaluated,
    BillingAlertEvaluationInProgress,
    next_billing_alert_check_at,
)
from products.billing_alerts.backend.models import BillingAlertConfiguration
from products.billing_alerts.backend.temporal.retry_policy import BILLING_ALERT_EVALUATE_RETRY_POLICY
from products.billing_alerts.backend.temporal.types import BillingAlertInfo, EvaluateBillingAlertBatchActivityInputs

MAX_DUE_BILLING_ALERTS_PER_TICK = 500
# Failure events are only recorded on the final attempt, so this must match the Temporal policy.
MAX_ACTIVITY_ATTEMPTS = BILLING_ALERT_EVALUATE_RETRY_POLICY.maximum_attempts
logger = structlog.get_logger(__name__)


def due_billing_alerts_q(now: datetime) -> QuerySet[BillingAlertConfiguration]:
    """Return the product-owned eligibility query for the hourly sweep."""
    return (
        BillingAlertConfiguration.objects.filter(enabled=True)
        .filter(Q(next_check_at__lte=now) | Q(next_check_at__isnull=True))
        .filter(Q(snoozed_until__isnull=True) | Q(snoozed_until__lte=now))
        .exclude(state=BillingAlertConfiguration.State.BROKEN)
    )


def _due_billing_alerts_for_sweep(now: datetime) -> QuerySet[BillingAlertConfiguration]:
    """Interleave due alerts by organization inside the global sweep budget."""
    return (
        due_billing_alerts_q(now)
        .annotate(
            _organization_rank=Window(
                expression=RowNumber(),
                partition_by=[F("organization_id")],
                order_by=[F("next_check_at").asc(nulls_first=True), F("id").asc()],
            )
        )
        .order_by(
            "_organization_rank",
            F("next_check_at").asc(nulls_first=True),
            "organization_id",
            "id",
        )
        .only("id", "organization_id", "baseline_window_days", "evaluation_delay_hours", "pending_evaluation_date")[
            :MAX_DUE_BILLING_ALERTS_PER_TICK
        ]
    )


def _group_key(alert: BillingAlertConfiguration, now: datetime) -> tuple[Any, ...]:
    return (
        str(alert.organization_id),
        alert.baseline_window_days,
        alert.evaluation_delay_hours,
        expected_evaluation_date(alert, now),
    )


def _reschedule_completed_alert(alert: BillingAlertConfiguration, now: datetime) -> None:
    next_check_at = next_billing_alert_check_at(alert, now)
    updated = (
        BillingAlertConfiguration.objects.filter(
            id=alert.id,
            organization_id=alert.organization_id,
            configuration_revision=alert.configuration_revision,
        )
        .filter(Q(next_check_at__lte=now) | Q(next_check_at__isnull=True))
        .update(next_check_at=next_check_at, pending_evaluation_date=None, retry_attempt_count=0, updated_at=now)
    )
    if updated:
        alert.next_check_at = next_check_at
        alert.pending_evaluation_date = None
        alert.retry_attempt_count = 0


def _record_group_failure(
    alert_group: list[BillingAlertConfiguration],
    error: Exception,
    *,
    now: datetime,
    is_transient_error: bool,
    reason: str,
) -> list[PendingBillingAlertDispatch]:
    first_alert = alert_group[0]
    alert_ids = [str(alert.id) for alert in alert_group]
    capture_exception(error, {"alert_ids": alert_ids, "feature": "billing_alerts"})
    logger.exception(
        "Billing alert group failure",
        alert_ids=alert_ids,
        organization_id=str(first_alert.organization_id),
        reason=reason,
    )

    pending_dispatches: list[PendingBillingAlertDispatch] = []
    for alert in alert_group:
        try:
            pending_dispatches.append(
                prepare_billing_alert_dispatch(
                    alert,
                    now=now,
                    error=error,
                    is_transient_error=is_transient_error,
                    failure_reason=reason,
                )
            )
        except BillingAlertAlreadyEvaluated:
            _reschedule_completed_alert(alert, now)
            continue
        except BillingAlertEvaluationInProgress:
            continue
        except Exception as dispatch_error:
            capture_exception(dispatch_error, {"alert_id": str(alert.id), "feature": "billing_alerts"})
            logger.exception("Billing alert failure event preparation failed", alert_id=str(alert.id))
            raise
    return pending_dispatches


def _evaluate_billing_alerts(
    inputs: EvaluateBillingAlertBatchActivityInputs,
    *,
    activity_attempt: int = MAX_ACTIVITY_ATTEMPTS,
) -> None:
    now = datetime.now(UTC)
    alerts = list(due_billing_alerts_q(now).filter(id__in=inputs.alert_ids).order_by("organization_id", "metric", "id"))
    grouped: dict[tuple[Any, ...], list[BillingAlertConfiguration]] = defaultdict(list)
    for alert in alerts:
        grouped[_group_key(alert, now)].append(alert)

    pending_dispatches: list[PendingBillingAlertDispatch] = []
    for alert_group in grouped.values():
        first_alert = alert_group[0]
        try:
            organization = Organization.objects.get(id=first_alert.organization_id)
        except Organization.DoesNotExist as e:
            pending_dispatches.extend(
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
            if activity_attempt < MAX_ACTIVITY_ATTEMPTS:
                raise
            pending_dispatches.extend(
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
            try:
                pending_dispatches.append(
                    prepare_billing_alert_dispatch(
                        alert,
                        now=now,
                        billing_response=billing_response,
                        query_duration_ms=query_duration_ms,
                    )
                )
            except BillingAlertAlreadyEvaluated:
                _reschedule_completed_alert(alert, now)
                continue
            except BillingAlertEvaluationInProgress:
                continue
            except Exception as dispatch_error:
                capture_exception(dispatch_error, {"alert_id": str(alert.id), "feature": "billing_alerts"})
                logger.exception("Billing alert evaluation preparation failed", alert_id=str(alert.id))
                raise

    commit_pending_billing_alert_dispatches(pending_dispatches)


@temporalio.activity.defn
async def discover_due_billing_alerts_activity() -> list[BillingAlertInfo]:
    @database_sync_to_async(thread_sensitive=False)
    def get_due_alerts() -> list[BillingAlertInfo]:
        now = datetime.now(UTC)
        alerts = _due_billing_alerts_for_sweep(now)
        # The key must match _group_key so the batch activity's per-group billing fetch lines up
        # with the workflow's batching.
        return [
            BillingAlertInfo(
                alert_id=str(alert.id),
                query_key=":".join(str(part) for part in _group_key(alert, now)),
            )
            for alert in alerts
        ]

    async with Heartbeater():
        return await get_due_alerts()


@temporalio.activity.defn
async def evaluate_billing_alert_batch_activity(inputs: EvaluateBillingAlertBatchActivityInputs) -> None:
    async with Heartbeater():
        await database_sync_to_async(_evaluate_billing_alerts, thread_sensitive=False)(
            inputs,
            activity_attempt=temporalio.activity.info().attempt,
        )
