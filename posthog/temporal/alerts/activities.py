from datetime import UTC, datetime

from django.db.models import Case, F, IntegerField, Q, Value, When

import structlog
import temporalio.activity

from posthog.schema import AlertCalculationInterval

from posthog.models import AlertConfiguration
from posthog.sync import database_sync_to_async
from posthog.temporal.alerts.types import (
    AlertInfo,
    EvaluateAlertActivityInputs,
    EvaluateAlertResult,
    NotifyAlertActivityInputs,
    PrepareAlertActivityInputs,
    PrepareAlertResult,
)

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def retrieve_due_alerts() -> list[AlertInfo]:
    @database_sync_to_async(thread_sensitive=False)
    def get_alerts() -> list[AlertInfo]:
        now = datetime.now(UTC)

        # Hourly before daily before weekly/monthly so the cheaper, more
        # time-sensitive checks get workers first when the due batch is large.
        calculation_interval_order = Case(
            When(calculation_interval=AlertCalculationInterval.HOURLY.value, then=Value(0)),
            When(calculation_interval=AlertCalculationInterval.DAILY.value, then=Value(1)),
            default=Value(2),
            output_field=IntegerField(),
        )

        alerts = (
            AlertConfiguration.objects.filter(
                Q(enabled=True, next_check_at__lte=now) | Q(enabled=True, next_check_at__isnull=True)
            )
            .filter(Q(snoozed_until__isnull=True) | Q(snoozed_until__lt=now))
            .filter(insight__deleted=False)
            .annotate(_interval_order=calculation_interval_order)
            .order_by("_interval_order", F("next_check_at").asc(nulls_first=True))
            .only("id", "team_id", "calculation_interval", "insight_id")
        )

        return [
            AlertInfo(
                alert_id=str(a.id),
                team_id=a.team_id,
                distinct_id=str(a.id),
                calculation_interval=a.calculation_interval,
                insight_id=a.insight_id,
            )
            for a in alerts
        ]

    return await get_alerts()


@temporalio.activity.defn
async def prepare_alert(inputs: PrepareAlertActivityInputs) -> PrepareAlertResult:
    """Load the alert, validate its config, and decide whether to evaluate."""
    raise NotImplementedError(
        "Alert check logic is ported in follow-up PR: https://github.com/PostHog/posthog/pull/53835"
    )


@temporalio.activity.defn
async def evaluate_alert(inputs: EvaluateAlertActivityInputs) -> EvaluateAlertResult:
    """Run the insight ClickHouse query, apply the state machine, persist an AlertCheck row."""
    raise NotImplementedError(
        "Alert check logic is ported in follow-up PR: https://github.com/PostHog/posthog/pull/53835"
    )


@temporalio.activity.defn
async def notify_alert(inputs: NotifyAlertActivityInputs) -> None:
    """Send notifications for a previously evaluated alert check (idempotent)."""
    raise NotImplementedError(
        "Alert check logic is ported in follow-up PR: https://github.com/PostHog/posthog/pull/53835"
    )
