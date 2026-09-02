from django.conf import settings

from temporalio.client import ScheduleActionStartWorkflow, ScheduleOverlapPolicy

from posthog.temporal.billing_usage_rollup.schedule import SCHEDULE_ID, WORKFLOW_NAME, build_schedule
from posthog.temporal.billing_usage_rollup.types import BillingUsageRecordsRollupInput


def test_billing_usage_rollup_schedule() -> None:
    schedule = build_schedule()
    assert isinstance(schedule.action, ScheduleActionStartWorkflow)
    assert schedule.action.workflow == WORKFLOW_NAME
    assert list(schedule.action.args) == [BillingUsageRecordsRollupInput()]
    assert schedule.action.id == SCHEDULE_ID
    assert schedule.action.task_queue == settings.ANALYTICS_PLATFORM_TASK_QUEUE
    assert schedule.policy.overlap == ScheduleOverlapPolicy.SKIP


def test_billing_usage_rollup_schedule_is_registered() -> None:
    from posthog.temporal.billing_usage_rollup.schedule import (  # noqa: PLC0415 — heavy registry import, kept off module load
        create_billing_usage_rollup_schedule,
    )
    from posthog.temporal.schedule import schedules  # noqa: PLC0415 — heavy registry import, kept off module load

    assert create_billing_usage_rollup_schedule in schedules
