import json
from dataclasses import asdict
from datetime import timedelta

import temporalio.workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, ApplicationError

from posthog.temporal.common.base import PostHogWorkflow

with temporalio.workflow.unsafe.imports_passed_through():
    from posthog.temporal.health_checks.rollups.activities import (
        ROLLUP_DAY_REFUSED_ERROR_TYPE,
        apply_daily_rollup_retention,
        plan_daily_rollup_run,
        run_daily_rollup_step,
    )
    from posthog.temporal.health_checks.rollups.inputs import DailyRollupWorkflowInputs, RollupPlan, RollupStepResult

STEP_RETRY_POLICY = RetryPolicy(
    maximum_attempts=3,
    initial_interval=timedelta(minutes=1),
    backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=10),
    non_retryable_error_types=[ROLLUP_DAY_REFUSED_ERROR_TYPE],
)
SHORT_RETRY_POLICY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=30))
HEARTBEAT_TIMEOUT = timedelta(minutes=5)


@temporalio.workflow.defn(name="daily-rollup-workflow")
class DailyRollupWorkflow(PostHogWorkflow):
    """Fill the daily health check rollups from ClickHouse into Postgres.

    The plan activity decides which days to fill, so the day policy can change without changing
    this workflow's commands. Every step runs even when an earlier one fails, and retention runs
    last. The workflow then fails if any step failed, which leaves each failed day as it was.
    """

    @staticmethod
    def parse_inputs(inputs: list[str]) -> DailyRollupWorkflowInputs:
        return DailyRollupWorkflowInputs(**json.loads(inputs[0])) if inputs else DailyRollupWorkflowInputs()

    @temporalio.workflow.run
    async def run(self, inputs: DailyRollupWorkflowInputs) -> dict:
        plan: RollupPlan = await temporalio.workflow.execute_activity(
            plan_daily_rollup_run,
            inputs,
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=SHORT_RETRY_POLICY,
        )

        results: list[RollupStepResult] = []
        failures: list[str] = []
        for step in plan.steps:
            try:
                result: RollupStepResult = await temporalio.workflow.execute_activity(
                    run_daily_rollup_step,
                    step,
                    start_to_close_timeout=timedelta(hours=2),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=STEP_RETRY_POLICY,
                )
                results.append(result)
            except ActivityError as error:
                failures.append(f"{step.table} {step.day}: {error.cause or error}")
                temporalio.workflow.logger.warning(
                    "Daily rollup step failed", extra={"table": step.table, "day": step.day, "error": str(error.cause)}
                )

        deleted_rows: dict[str, int] = {}
        for table in plan.retention_tables:
            try:
                deleted_rows[table] = await temporalio.workflow.execute_activity(
                    apply_daily_rollup_retention,
                    table,
                    start_to_close_timeout=timedelta(minutes=30),
                    heartbeat_timeout=HEARTBEAT_TIMEOUT,
                    retry_policy=SHORT_RETRY_POLICY,
                )
            except ActivityError as error:
                failures.append(f"{table} retention: {error.cause or error}")

        if failures:
            raise ApplicationError(
                f"{len(failures)} daily rollup step(s) failed: " + "; ".join(failures), non_retryable=True
            )

        return {"steps": [asdict(result) for result in results], "deleted_rows": deleted_rows}
