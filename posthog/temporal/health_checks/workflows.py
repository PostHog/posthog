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
        get_team_id_page,
        push_health_check_metrics_activity,
        run_health_check_batch,
    )
    from posthog.temporal.health_checks.models import (
        BatchResult,
        HealthCheckRunProgress,
        HealthCheckThresholdExceeded,
        HealthCheckWorkflowInputs,
    )

ACTIVITY_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(seconds=30),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=5),
)

PAGED_RUN_PATCH = "health-check-paged-run-2026-10"
# Temporal terminates a workflow at 51,200 history events, and a run that ends that way sends no metrics
# and raises nothing. A run continues as new well below the limit, even when the server never suggests it.
MAX_HISTORY_EVENTS_PER_RUN = 10_000


@temporalio.workflow.defn(name="health-check-workflow")
class HealthCheckWorkflow(PostHogWorkflow):
    """Run one health check over every scheduled team.

    Team ids arrive one page at a time, and the run continues as new between pages when its history
    grows. So the history and every payload stay bounded whatever the team count and the batch size.
    `inputs.progress` carries the totals across, and only the last run reports them.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> HealthCheckWorkflowInputs:
        return HealthCheckWorkflowInputs(**json.loads(inputs[0]))

    @temporalio.workflow.run
    async def run(self, inputs: HealthCheckWorkflowInputs) -> dict:
        if not temporalio.workflow.patched(PAGED_RUN_PATCH):
            return await self._run_unpaged(inputs)

        progress = inputs.progress or HealthCheckRunProgress()
        semaphore = asyncio.Semaphore(inputs.max_concurrent)
        while True:
            page = await temporalio.workflow.execute_activity(
                get_team_id_page,
                args=[inputs, progress.after_team_id],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=ACTIVITY_RETRY_POLICY,
            )
            if page.stopped_by_kill_switch:
                # The run sends no metrics, so monitoring still shows the last run that checked every team.
                return {"kind": inputs.kind, "total_teams": progress.totals.batch_size, "stopped_by_kill_switch": True}
            batches = [
                page.team_ids[start : start + inputs.batch_size]
                for start in range(0, len(page.team_ids), inputs.batch_size)
            ]
            progress = await self._run_batches(inputs, batches, progress, semaphore)
            if page.next_after_team_id is None:
                break
            progress = dataclasses.replace(progress, after_team_id=page.next_after_team_id)
            info = temporalio.workflow.info()
            if info.is_continue_as_new_suggested() or info.get_current_history_length() >= MAX_HISTORY_EVENTS_PER_RUN:
                temporalio.workflow.continue_as_new(dataclasses.replace(inputs, progress=progress))

        return await self._finish(inputs, progress)

    async def _run_unpaged(self, inputs: HealthCheckWorkflowInputs) -> dict:
        """The run before PAGED_RUN_PATCH, kept so open runs replay. Delete it and `get_team_id_batches` after one deploy."""
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
        progress = await self._run_batches(inputs, batches, HealthCheckRunProgress(), semaphore)
        return await self._finish(inputs, progress)

    async def _run_batches(
        self,
        inputs: HealthCheckWorkflowInputs,
        batches: list[list[int]],
        progress: HealthCheckRunProgress,
        semaphore: asyncio.Semaphore,
    ) -> HealthCheckRunProgress:
        async def _run_batch(batch: list[int]) -> dict:
            async with semaphore:
                return await temporalio.workflow.execute_activity(
                    run_health_check_batch,
                    args=[batch, inputs.kind, inputs.dry_run],
                    start_to_close_timeout=timedelta(minutes=10),
                    retry_policy=ACTIVITY_RETRY_POLICY,
                )

        results = await asyncio.gather(*[_run_batch(b) for b in batches], return_exceptions=True)

        totals = dataclasses.replace(progress.totals)
        failed_batches = 0
        for batch, r in zip(batches, results):
            if isinstance(r, BaseException):
                failed_batches += 1
                totals += BatchResult(batch_size=len(batch), teams_failed=len(batch))
            else:
                totals += BatchResult(**r)

        return dataclasses.replace(
            progress,
            totals=totals,
            batches=progress.batches + len(batches),
            failed_batches=progress.failed_batches + failed_batches,
        )

    async def _finish(self, inputs: HealthCheckWorkflowInputs, progress: HealthCheckRunProgress) -> dict:
        totals = progress.totals
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
            "batches": progress.batches,
            "failed_batches": progress.failed_batches,
            "issues_upserted": totals.issues_upserted,
            "issues_resolved": totals.issues_resolved,
            "teams_with_issues": totals.teams_with_issues,
            "teams_healthy": totals.teams_healthy,
            "duration_seconds": totals.total_duration,
        }
