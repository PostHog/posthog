from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from time import perf_counter
from typing import Any

from django.utils import timezone

from posthog.cloud_utils import get_cached_instance_license
from posthog.models import Organization, Team

from products.billing_alerts.backend.models import BillingAlertConfiguration

from ee.billing.billing_manager import BillingManager


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
    query_duration_ms: int | None = None


class BillingAlertEvaluationError(Exception):
    pass


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _daily_totals(response: dict[str, Any]) -> dict[date, Decimal]:
    totals: dict[date, Decimal] = defaultdict(Decimal)
    for series in response.get("results", []):
        dates = series.get("dates", [])
        values = series.get("data", [])
        for date_value, value in zip(dates, values):
            totals[date.fromisoformat(str(date_value)[:10])] += _decimal(value)
    return dict(totals)


def validate_billing_response(response: dict[str, Any]) -> None:
    if isinstance(response.get("results"), list) and response.get("status") in (None, "ok"):
        return

    detail = (
        response.get("detail") or response.get("error") or response.get("message") or "No billing timeseries returned."
    )
    code = response.get("code") or response.get("type") or response.get("status") or "invalid_billing_response"
    raise BillingAlertEvaluationError(f"Billing service returned {code}: {detail}")


def expected_evaluation_date(alert: BillingAlertConfiguration, now: datetime | None = None) -> date:
    now = now or timezone.now()
    delayed_now = now.astimezone(UTC) - timedelta(hours=alert.evaluation_delay_hours)
    return delayed_now.date() - timedelta(days=1)


def _teams_map(organization: Organization) -> dict[int, str]:
    return {team.id: team.name for team in Team.objects.filter(organization=organization).only("id", "name")}


def billing_params(
    alert: BillingAlertConfiguration,
    organization: Organization,
    now: datetime | None = None,
) -> dict[str, Any]:
    evaluation_date = expected_evaluation_date(alert, now)
    evaluation_start = evaluation_date - timedelta(days=alert.baseline_window_days)
    params: dict[str, Any] = {
        "start_date": evaluation_start.isoformat(),
        "end_date": evaluation_date.isoformat(),
        "interval": "day",
        "teams_map": _teams_map(organization),
    }
    if alert.usage_types:
        params["usage_types"] = alert.usage_types
    if alert.team_ids:
        params["team_ids"] = alert.team_ids
    return params


def fetch_billing_data(
    alert: BillingAlertConfiguration,
    organization: Organization,
    *,
    manager: BillingManager | None = None,
    now: datetime | None = None,
) -> tuple[dict[str, Any], int]:
    manager = manager or BillingManager(get_cached_instance_license())
    params = billing_params(alert, organization, now)
    start = perf_counter()
    if alert.metric == BillingAlertConfiguration.Metric.SPEND:
        response = manager.get_spend_data(organization, params)
    else:
        response = manager.get_usage_data(organization, params)
    return response, int((perf_counter() - start) * 1000)


def evaluate_billing_alert(
    alert: BillingAlertConfiguration,
    *,
    manager: BillingManager | None = None,
    now: datetime | None = None,
    billing_response: dict[str, Any] | None = None,
    query_duration_ms: int | None = None,
) -> BillingAlertEvaluation:
    now = now or timezone.now()
    organization = Organization.objects.get(id=alert.organization_id)
    expected_date = expected_evaluation_date(alert, now)
    period_start = datetime.combine(expected_date, datetime.min.time(), tzinfo=UTC)
    period_end = period_start + timedelta(days=1)

    if billing_response is None:
        billing_response, query_duration_ms = fetch_billing_data(alert, organization, manager=manager, now=now)

    validate_billing_response(billing_response)
    totals = _daily_totals(billing_response)
    payload: dict[str, Any] = {
        "expected_evaluation_date": expected_date.isoformat(),
        "available_dates": [day.isoformat() for day in sorted(totals)],
        "metric": alert.metric,
        "threshold_type": alert.threshold_type,
        "status": billing_response.get("status"),
    }

    if expected_date not in totals:
        return BillingAlertEvaluation(
            evaluation_date=expected_date,
            period_start=period_start,
            period_end=period_end,
            current_value=None,
            baseline_value=None,
            absolute_delta=None,
            relative_delta_percentage=None,
            threshold_breached=False,
            reason=f"Billing data for {expected_date.isoformat()} was not available yet.",
            payload=payload,
            query_duration_ms=query_duration_ms,
        )

    current_value = totals[expected_date]
    baseline_dates = [expected_date - timedelta(days=offset) for offset in range(alert.baseline_window_days, 0, -1)]
    available_baseline_dates = [day for day in baseline_dates if day in totals]
    payload["baseline_dates"] = [day.isoformat() for day in available_baseline_dates]

    if not available_baseline_dates:
        return BillingAlertEvaluation(
            evaluation_date=expected_date,
            period_start=period_start,
            period_end=period_end,
            current_value=current_value,
            baseline_value=None,
            absolute_delta=None,
            relative_delta_percentage=None,
            threshold_breached=False,
            reason=f"No baseline data was available before {expected_date.isoformat()}.",
            payload=payload,
            query_duration_ms=query_duration_ms,
        )

    baseline_value = sum((totals[day] for day in available_baseline_dates), Decimal("0")) / Decimal(
        len(available_baseline_dates)
    )
    absolute_delta = current_value - baseline_value
    relative_delta_percentage = None
    if baseline_value > 0:
        relative_delta_percentage = (absolute_delta / baseline_value) * Decimal("100")

    if current_value < alert.minimum_value:
        return BillingAlertEvaluation(
            evaluation_date=expected_date,
            period_start=period_start,
            period_end=period_end,
            current_value=current_value,
            baseline_value=baseline_value,
            absolute_delta=absolute_delta,
            relative_delta_percentage=relative_delta_percentage,
            threshold_breached=False,
            reason=f"Current value {current_value} is below the minimum value {alert.minimum_value}.",
            payload=payload,
            query_duration_ms=query_duration_ms,
        )

    if alert.threshold_type == BillingAlertConfiguration.ThresholdType.ABSOLUTE_VALUE:
        threshold_value = alert.threshold_value or Decimal("0")
        breached = current_value >= threshold_value
        reason = f"Current value {current_value} {'met' if breached else 'did not meet'} threshold {threshold_value}."
    elif alert.threshold_type == BillingAlertConfiguration.ThresholdType.ABSOLUTE_INCREASE:
        threshold_value = alert.threshold_value or Decimal("0")
        breached = absolute_delta >= threshold_value
        reason = (
            f"Current value {current_value} changed by {absolute_delta} from baseline {baseline_value}; "
            f"threshold is {threshold_value}."
        )
    else:
        if baseline_value <= 0:
            return BillingAlertEvaluation(
                evaluation_date=expected_date,
                period_start=period_start,
                period_end=period_end,
                current_value=current_value,
                baseline_value=baseline_value,
                absolute_delta=absolute_delta,
                relative_delta_percentage=None,
                threshold_breached=False,
                reason="Baseline value is zero, so a relative increase cannot be calculated.",
                payload=payload,
                query_duration_ms=query_duration_ms,
            )
        threshold_percentage = alert.threshold_percentage or Decimal("0")
        threshold_value = baseline_value * (Decimal("1") + (threshold_percentage / Decimal("100")))
        breached = current_value >= max(alert.minimum_value, threshold_value)
        reason = (
            f"Current value {current_value} was {relative_delta_percentage.quantize(Decimal('0.01'))}% "
            f"above baseline {baseline_value.quantize(Decimal('0.000001'))}; "
            f"threshold is {threshold_percentage}%."
        )

    return BillingAlertEvaluation(
        evaluation_date=expected_date,
        period_start=period_start,
        period_end=period_end,
        current_value=current_value,
        baseline_value=baseline_value,
        absolute_delta=absolute_delta,
        relative_delta_percentage=relative_delta_percentage,
        threshold_breached=breached,
        reason=reason,
        payload=payload,
        query_duration_ms=query_duration_ms,
    )
