from datetime import UTC, datetime

from django.db.models import Case, F, IntegerField, Q, Value, When

import structlog
import temporalio.activity

from posthog.schema import AlertCalculationInterval

from posthog.models import AlertConfiguration
from posthog.sync import database_sync_to_async
from posthog.temporal.alerts.types import (
    AlertInfo,
    EnumerateDueAlertsActivityInputs,
    EvaluateAlertActivityInputs,
    EvaluateAlertResult,
    NotifyAlertActivityInputs,
    PrepareAlertActivityInputs,
    PrepareAlertResult,
)

logger = structlog.get_logger(__name__)

# The prepare/evaluate/notify activities are intentional stubs — their
# bodies are ported from posthog/tasks/alerts/checks.py in a follow-up PR:
# https://github.com/PostHog/posthog/pull/53835


@temporalio.activity.defn
async def enumerate_due_alerts_activity(
    inputs: EnumerateDueAlertsActivityInputs,
) -> list[AlertInfo]:
    """Find all due alerts and return minimal metadata for fan-out.

    Mirrors the queryset built by `check_alerts_task` in
    `posthog/tasks/alerts/checks.py` but trimmed to the fields the workflow
    needs to start child workflows. The per-team grouping/chaining from
    `check_alerts_task` is intentionally dropped — under Temporal, concurrency
    is bounded by ClickHouse query tagging and workload management rather
    than per-team serialisation.
    """

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

        # The `is_calculating=False` filter from the Celery version is intentionally
        # dropped: Temporal's deterministic child workflow ID (`check-alert-{id}`)
        # enforces at-most-one-running-check per alert via WorkflowAlreadyStartedError.
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
async def prepare_alert_activity(inputs: PrepareAlertActivityInputs) -> PrepareAlertResult:
    """Load the alert, validate its config, and decide whether to evaluate."""
    raise NotImplementedError(
        "Alert check logic is ported in follow-up PR: https://github.com/PostHog/posthog/pull/53835"
    )


@temporalio.activity.defn
async def evaluate_alert_activity(inputs: EvaluateAlertActivityInputs) -> EvaluateAlertResult:
    """Run the insight ClickHouse query, apply the state machine, persist an AlertCheck row."""
    raise NotImplementedError(
        "Alert check logic is ported in follow-up PR: https://github.com/PostHog/posthog/pull/53835"
    )


@temporalio.activity.defn
async def notify_alert_activity(inputs: NotifyAlertActivityInputs) -> None:
    """Send notifications for a previously evaluated alert check (idempotent)."""
    raise NotImplementedError(
        "Alert check logic is ported in follow-up PR: https://github.com/PostHog/posthog/pull/53835"
    )
