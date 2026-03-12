import json
import asyncio
import dataclasses
from datetime import timedelta

import temporalio.workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from posthog.temporal.health_checks.activities import (
        get_team_id_batches,
        push_health_check_metrics_activity,
        run_health_check_batch,
    )
    from posthog.temporal.health_checks.models import (
        BatchResult,
        HealthCheckThresholdExceeded,
        HealthCheckWorkflowInputs,
    )

ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
)


@temporalio.workflow.defn(name="health-check-workflow")
class HealthCheckWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> HealthCheckWorkflowInputs:
        return HealthCheckWorkflowInputs(**json.loads(inputs[0]))

    @temporalio.workflow.run
    async def run(self, inputs: HealthCheckWorkflowInputs) -> dict:
        batches = await temporalio.workflow.execute_activity(
            get_team_id_batches,
            inputs,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=ACTIVITY_RETRY_POLICY,
        )

        if not batches:
            return {
                "kind": inputs.kind,
                "total_teams": 0,
                "batches": 0,
            }

        semaphore = asyncio.Semaphore(inputs.max_concurrent)

        async def _run_batch(batch: list[int]) -> dict:
            async with semaphore:
                return await temporalio.workflow.execute_activity(
                    run_health_check_batch,
                    args=[batch, inputs.kind, inputs.dry_run],
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )

        results = await asyncio.gather(*[_run_batch(b) for b in batches], return_exceptions=True)

        totals = BatchResult()
        failed_batches = 0
        for batch, r in zip(batches, results):
            if isinstance(r, BaseException):
                failed_batches += 1
                totals += BatchResult(batch_size=len(batch), teams_failed=len(batch))
            else:
                batch_result = BatchResult(**r)
                totals += batch_result

        threshold_exceeded = totals.batch_size > 0 and totals.not_processed_rate > inputs.not_processed_threshold
        await temporalio.workflow.execute_activity(
            push_health_check_metrics_activity,
            args=[inputs.kind, dataclasses.asdict(totals), not threshold_exceeded],
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=ACTIVITY_RETRY_POLICY,
        )

        if threshold_exceeded:
            not_processed = totals.teams_skipped + totals.teams_failed
            raise HealthCheckThresholdExceeded(
                f"Health check '{inputs.kind}': {not_processed:,}/{totals.batch_size:,} teams not processed "
                f"({totals.not_processed_rate:.1%}), exceeds threshold {inputs.not_processed_threshold:.1%} "
                f"(skipped={totals.teams_skipped:,}, failed={totals.teams_failed:,})"
            )

        return {
            "kind": inputs.kind,
            "total_teams": totals.batch_size,
            "batches": len(batches),
            "failed_batches": failed_batches,
            "issues_upserted": totals.issues_upserted,
            "issues_resolved": totals.issues_resolved,
            "teams_with_issues": totals.teams_with_issues,
            "teams_healthy": totals.teams_healthy,
            "duration_seconds": totals.total_duration,
        }
