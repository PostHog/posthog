# IMPORTANT — module-level imports policy:
#
# This module is loaded by both the Temporal worker (which runs activities
# outside the sandbox) AND, transitively via posthog/temporal/alerts/__init__.py,
# the workflow sandbox import path. Activities can use any imports, but if a
# module is loaded into the workflow sandbox, all Django ORM and Django app
# registry imports must NOT be at module top — they need to be inside function
# bodies.
#
# Rule: at module top, only import stdlib, temporalio, structlog, asgiref,
# and the local types from posthog.temporal.alerts.types. ALL Django imports
# (models, F/Q query expressions, transaction helpers, etc.) go inside the
# function body that needs them, even if they look "standalone."

from datetime import UTC, datetime

import structlog
import temporalio.activity

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
#
# Until then they raise NotImplementedError; the workflow is registered on
# the analytics-platform Temporal worker but no schedule points at it yet,
# so nothing in production reaches these stubs.


@temporalio.activity.defn
async def enumerate_due_alerts_activity(
    inputs: EnumerateDueAlertsActivityInputs,
) -> list[AlertInfo]:
    """Find all due alerts and return minimal metadata for fan-out.

    Mirrors the query at posthog/tasks/alerts/checks.py:159-181 but trimmed to
    the fields the workflow needs to start child workflows. The per-team
    grouping/chaining from check_alerts_task is intentionally dropped — under
    Temporal, concurrency is bounded by ClickHouse query tagging and workload
    management rather than per-team serialisation.
    """
    return await database_sync_to_async(_enumerate_due_alerts_sync)()


def _enumerate_due_alerts_sync() -> list[AlertInfo]:
    # Late imports per the module-top policy above.
    from typing import cast

    from django.db.models import F, Q

    from posthog.schema import AlertCalculationInterval

    from posthog.models import AlertConfiguration
    from posthog.tasks.alerts.utils import calculation_interval_to_order

    now = datetime.now(UTC)

    # The `is_calculating=False` filter from the Celery version is intentionally
    # dropped: Temporal's deterministic child workflow ID (`check-alert-{id}`)
    # enforces at-most-one-running-check per alert via WorkflowAlreadyStartedError.
    alerts = (
        AlertConfiguration.objects.filter(
            Q(enabled=True, next_check_at__lte=now) | Q(enabled=True, next_check_at__isnull=True)
        )
        .filter(Q(snoozed_until__isnull=True) | Q(snoozed_until__lt=now))
        .filter(insight__deleted=False)
        .order_by(F("next_check_at").asc(nulls_first=True))
        .only("id", "team_id", "calculation_interval", "insight_id")
    )

    sorted_alerts = sorted(
        alerts,
        key=lambda a: calculation_interval_to_order(cast(AlertCalculationInterval | None, a.calculation_interval)),
    )

    return [
        AlertInfo(
            alert_id=str(a.id),
            team_id=a.team_id,
            distinct_id=str(a.id),
            calculation_interval=a.calculation_interval,
            insight_id=a.insight_id,
        )
        for a in sorted_alerts
    ]


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
