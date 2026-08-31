import asyncio
import datetime as dt

from temporalio import workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow

from ..activities.finalize_check_suite import (
    finalize_check_suite_activity,
    mark_check_suite_empty_activity,
    mark_check_suite_failed_activity,
)
from ..activities.prepare_check_suite import prepare_check_suite_activity
from ..activities.run_check_batch import run_check_batch_activity
from ..contracts import (
    BatchOutcome,
    CheckSuiteResult,
    FinalizeCheckSuiteInputs,
    MarkSuiteFailedInputs,
    PreparedSuite,
    RunCheckBatchInputs,
    RunCheckSuiteInputs,
)

MAX_CONCURRENT_BATCHES = 4


@workflow.defn(name="data-quality-run-suite")
class RunCheckSuiteWorkflow(PostHogWorkflow):
    """Run a batch of data quality checks and record a report.

    Individual check failures are data, not workflow failures: a suite completes as long as it
    could load its checks, whatever they found.
    """

    inputs_cls = RunCheckSuiteInputs

    @workflow.run
    async def run(self, inputs: RunCheckSuiteInputs) -> CheckSuiteResult:
        suite_run_id = inputs.suite_run_id
        try:
            prepared: PreparedSuite = await workflow.execute_activity(
                prepare_check_suite_activity,
                inputs,
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
            suite_run_id = prepared.suite_run_id

            if not prepared.batches:
                return await workflow.execute_activity(
                    mark_check_suite_empty_activity,
                    FinalizeCheckSuiteInputs(team_id=inputs.team_id, suite_run_id=prepared.suite_run_id, outcomes=[]),
                    start_to_close_timeout=dt.timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )

            outcomes = await self._run_batches(inputs, prepared)
            return await workflow.execute_activity(
                finalize_check_suite_activity,
                FinalizeCheckSuiteInputs(team_id=inputs.team_id, suite_run_id=prepared.suite_run_id, outcomes=outcomes),
                start_to_close_timeout=dt.timedelta(minutes=2),
                retry_policy=RetryPolicy(maximum_attempts=3),
            )
        except Exception as error:
            if suite_run_id:
                await workflow.execute_activity(
                    mark_check_suite_failed_activity,
                    MarkSuiteFailedInputs(team_id=inputs.team_id, suite_run_id=suite_run_id, error=str(error)),
                    start_to_close_timeout=dt.timedelta(minutes=1),
                    retry_policy=RetryPolicy(maximum_attempts=3),
                )
            raise

    async def _run_batches(self, inputs: RunCheckSuiteInputs, prepared: PreparedSuite) -> list[BatchOutcome]:
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_BATCHES)
        staged_saved_query_id = (
            inputs.saved_query_ids[0] if inputs.staged_queryable_folder and len(inputs.saved_query_ids) == 1 else None
        )

        async def _run(check_ids: list[str]) -> BatchOutcome:
            async with semaphore:
                return await workflow.execute_activity(
                    run_check_batch_activity,
                    RunCheckBatchInputs(
                        team_id=inputs.team_id,
                        suite_run_id=prepared.suite_run_id,
                        check_ids=check_ids,
                        staged_queryable_folder=inputs.staged_queryable_folder if staged_saved_query_id else None,
                        staged_saved_query_id=staged_saved_query_id,
                    ),
                    start_to_close_timeout=dt.timedelta(minutes=30),
                    heartbeat_timeout=dt.timedelta(minutes=2),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )

        return list(await asyncio.gather(*[_run(batch) for batch in prepared.batches]))
