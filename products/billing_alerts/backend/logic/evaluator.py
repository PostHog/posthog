from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import Any

from django.utils import timezone

from posthog.cloud_utils import get_cached_instance_license
from posthog.models import Organization

from products.billing_alerts.backend.models import BillingAlertConfiguration

from ee.billing.billing_manager import BillingManager

# Billing period totals the evaluator reads for each supported metric. Both are
# after-discount amounts so alerts fire on what the customer actually owes.
_METRIC_AMOUNT_FIELD: dict[str, str] = {
    BillingAlertConfiguration.Metric.SPEND: "current_total_amount_usd_after_discount",
    BillingAlertConfiguration.Metric.PROJECTED_SPEND: "projected_total_amount_usd_with_limit_after_discount",
}


@dataclass(frozen=True)
class BillingAlertEvaluation:
    evaluation_date: date
    period_start: datetime
    period_end: datetime
    current_value: Decimal | None
    baseline_value: Decimal | None
    absolute_delta: Decimal | None
    relative_delta_percentage: Decimal | None
    threshold_breached: bool
    reason: str
    payload: dict[str, Any]
    is_inconclusive: bool = False
    query_duration_ms: int | None = None


class BillingAlertEvaluationError(Exception):
    pass


def _validate_supported_metric(alert: BillingAlertConfiguration) -> None:
    if alert.metric not in _METRIC_AMOUNT_FIELD or alert.currency != "USD":
        raise BillingAlertEvaluationError("Billing alerts currently support USD spend only.")
    if alert.threshold_type != BillingAlertConfiguration.ThresholdType.ABSOLUTE_VALUE:
        raise BillingAlertEvaluationError(
            "Billing alerts currently support absolute value thresholds only. "
            "Increase-over-baseline thresholds are not available for billing-period totals."
        )


def _decimal(value: Any, *, field: str) -> Decimal:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise BillingAlertEvaluationError(f"Billing status returned an invalid amount for {field}: {value!r}.")
    if not parsed.is_finite():
        raise BillingAlertEvaluationError(f"Billing status returned an invalid amount for {field}: {value!r}.")
    return parsed


def _parse_period_boundary(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def expected_evaluation_date(alert: BillingAlertConfiguration, now: datetime | None = None) -> date:
    if alert.pending_evaluation_date is not None:
        return alert.pending_evaluation_date
    now = now or timezone.now()
    delayed_now = now.astimezone(UTC) - timedelta(hours=alert.evaluation_delay_hours)
    return delayed_now.date() - timedelta(days=1)


def fetch_billing_data(
    alert: BillingAlertConfiguration,
    organization: Organization,
    *,
    manager: BillingManager | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], int]:
    manager = manager or BillingManager(get_cached_instance_license())
    start = perf_counter()
    response = manager.get_billing_status_for_alerts(organization)
    return response, int((perf_counter() - start) * 1000)


def _customer(billing_response: dict[str, Any]) -> dict[str, Any]:
    customer = billing_response.get("customer")
    if not isinstance(customer, dict):
        raise BillingAlertEvaluationError("Billing status did not include customer data.")
    return customer


def evaluate_billing_alert(
    alert: BillingAlertConfiguration,
    *,
    manager: BillingManager | None = None,
    now: datetime | None = None,
    billing_response: dict[str, Any] | None = None,
    query_duration_ms: int | None = None,
) -> BillingAlertEvaluation:
    _validate_supported_metric(alert)
    now = now or timezone.now()
    expected_date = expected_evaluation_date(alert, now)

    if billing_response is None:
        organization = Organization.objects.get(id=alert.organization_id)
        billing_response, query_duration_ms = fetch_billing_data(alert, organization, manager=manager, now=now)

    customer = _customer(billing_response)
    billing_period = customer.get("billing_period") or {}
    # Fall back to the evaluation date's UTC day when the billing period is absent (e.g. a
    # customer with no active subscription), so the recorded event still has a period window.
    default_start = datetime.combine(expected_date, datetime.min.time(), tzinfo=UTC)
    period_start = _parse_period_boundary(billing_period.get("current_period_start")) or default_start
    period_end = _parse_period_boundary(billing_period.get("current_period_end")) or (default_start + timedelta(days=1))

    amount_field = _METRIC_AMOUNT_FIELD[alert.metric]
    raw_amount = customer.get(amount_field)

    payload: dict[str, Any] = {
        "expected_evaluation_date": expected_date.isoformat(),
        "metric": alert.metric,
        "threshold_type": alert.threshold_type,
        "amount_field": amount_field,
        "period_start": billing_period.get("current_period_start"),
        "period_end": billing_period.get("current_period_end"),
        "has_active_subscription": customer.get("has_active_subscription"),
    }

    def result(*, reason: str, **overrides: Any) -> BillingAlertEvaluation:
        values: dict[str, Any] = {
            "evaluation_date": expected_date,
            "period_start": period_start,
            "period_end": period_end,
            "current_value": None,
            "baseline_value": None,
            "absolute_delta": None,
            "relative_delta_percentage": None,
            "threshold_breached": False,
            "payload": payload,
            "query_duration_ms": query_duration_ms,
            **overrides,
        }
        return BillingAlertEvaluation(reason=reason, **values)

    if raw_amount is None:
        return result(
            reason="Billing status did not include a spend total for this billing period yet.",
            is_inconclusive=True,
        )

    current_value = _decimal(raw_amount, field=amount_field)

    if current_value < alert.minimum_value:
        return result(
            reason=f"Current value {current_value} is below the minimum value {alert.minimum_value}.",
            current_value=current_value,
        )

    threshold_value = alert.threshold_value or Decimal("0")
    breached = current_value >= threshold_value
    return result(
        reason=f"Current value {current_value} {'met' if breached else 'did not meet'} threshold {threshold_value}.",
        current_value=current_value,
        threshold_breached=breached,
    )
