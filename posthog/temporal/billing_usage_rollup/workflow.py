from datetime import timedelta

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.billing_usage_rollup.types import BillingUsageRecordsRollupInput
from posthog.temporal.common.base import PostHogWorkflow

with workflow.unsafe.imports_passed_through():
    from posthog.temporal.billing_usage_rollup.activities import rollup_billing_usage_records


@workflow.defn(name="rollup-billing-usage-records")
class RollupBillingUsageRecordsWorkflow(PostHogWorkflow):
    inputs_cls = BillingUsageRecordsRollupInput

    @workflow.run
    async def run(self, input: BillingUsageRecordsRollupInput) -> None:
        await workflow.execute_activity(
            rollup_billing_usage_records,
            input,
            start_to_close_timeout=timedelta(hours=2),
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(minutes=5)),
        )
