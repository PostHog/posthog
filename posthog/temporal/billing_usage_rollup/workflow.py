from datetime import UTC, date, datetime, time, timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

from posthog.temporal.billing_usage_rollup.types import (
    BILLING_USAGE_RECORDS_ROLLUP_DELAY_DAYS,
    BillingUsageRecordsRollupInput,
    BillingUsageRecordsRollupWorkflowInput,
)
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.utils import get_scheduled_start_time

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.billing_usage_rollup.activities import rollup_billing_usage_records


ROLLUP_HOUR_UTC = 5


def latest_safe_rollup_day(now: datetime) -> date:
    return (now - timedelta(days=BILLING_USAGE_RECORDS_ROLLUP_DELAY_DAYS + 1)).date()


def next_rollup_day(last_completed_day: date, now: datetime) -> date | None:
    candidate = last_completed_day + timedelta(days=1)
    return candidate if candidate <= latest_safe_rollup_day(now) else None


def time_until_next_rollup(now: datetime) -> timedelta:
    next_rollup = datetime.combine(now.date(), time(ROLLUP_HOUR_UTC), UTC)
    if now >= next_rollup:
        next_rollup += timedelta(days=1)
    return next_rollup - now


@workflow.defn(name="rollup-billing-usage-records")
class RollupBillingUsageRecordsWorkflow(PostHogWorkflow):
    inputs_cls = BillingUsageRecordsRollupWorkflowInput

    @workflow.run
    async def run(self, input: BillingUsageRecordsRollupWorkflowInput) -> None:
        last_completed_day = (
            date.fromisoformat(input.last_completed_day)
            if input.last_completed_day is not None
            else latest_safe_rollup_day(get_scheduled_start_time()) - timedelta(days=1)
        )
        day = next_rollup_day(last_completed_day, workflow.now())

        if day is None:
            await workflow.sleep(time_until_next_rollup(workflow.now()))
            workflow.continue_as_new(
                BillingUsageRecordsRollupWorkflowInput(last_completed_day=last_completed_day.isoformat())
            )

        assert day is not None

        try:
            await workflow.execute_activity(
                rollup_billing_usage_records,
                BillingUsageRecordsRollupInput(day=day.isoformat()),
                start_to_close_timeout=timedelta(hours=2),
                heartbeat_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(minutes=5)),
            )
        except ActivityError:
            await workflow.sleep(timedelta(hours=1))
            workflow.continue_as_new(
                BillingUsageRecordsRollupWorkflowInput(last_completed_day=last_completed_day.isoformat())
            )

        workflow.continue_as_new(BillingUsageRecordsRollupWorkflowInput(last_completed_day=day.isoformat()))
