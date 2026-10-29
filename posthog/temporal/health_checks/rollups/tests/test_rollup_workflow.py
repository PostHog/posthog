import uuid
import logging
import datetime as dt

import pytest

import temporalio.activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.health_checks.rollups.activities import ROLLUP_DAY_REFUSED_ERROR_TYPE
from posthog.temporal.health_checks.rollups.inputs import (
    DailyRollupWorkflowInputs,
    RollupPlan,
    RollupStep,
    RollupStepResult,
)
from posthog.temporal.health_checks.rollups.workflows import DailyRollupWorkflow

PLAN = RollupPlan(
    steps=[
        RollupStep(table="a", day="2026-10-28", mode="publish"),
        RollupStep(table="a", day="2026-10-27", mode="refresh"),
        RollupStep(table="b", day="2026-10-28", mode="publish"),
    ],
    retention_tables=["a", "b"],
)


@pytest.fixture(autouse=True)
def _temporal_logs_at_info() -> None:
    logging.getLogger("temporalio.workflow").setLevel(logging.INFO)
    logging.getLogger("temporalio.activity").setLevel(logging.INFO)


@pytest.mark.asyncio
async def test_refused_day_fails_the_run_only_after_every_step_and_retention_ran() -> None:
    step_attempts: list[tuple[str, str, int]] = []
    retention_tables: list[str] = []

    @temporalio.activity.defn(name="plan_daily_rollup_run")
    async def plan(_inputs: DailyRollupWorkflowInputs) -> RollupPlan:
        return PLAN

    @temporalio.activity.defn(name="run_daily_rollup_step")
    async def run_step(step: RollupStep) -> RollupStepResult:
        step_attempts.append((step.table, step.day, temporalio.activity.info().attempt))
        if step.table == "a" and step.mode == "publish":
            raise ApplicationError("the day has no rows", type=ROLLUP_DAY_REFUSED_ERROR_TYPE, non_retryable=True)
        return RollupStepResult(table=step.table, day=step.day, outcome="published", rows=1, events=1)

    @temporalio.activity.defn(name="apply_daily_rollup_retention")
    async def retention(table: str) -> int:
        retention_tables.append(table)
        return 0

    async with await WorkflowEnvironment.start_time_skipping() as env:
        task_queue = str(uuid.uuid4())
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[DailyRollupWorkflow],
            activities=[plan, run_step, retention],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError) as failure:
                await env.client.execute_workflow(
                    DailyRollupWorkflow.run,
                    DailyRollupWorkflowInputs(),
                    id=str(uuid.uuid4()),
                    task_queue=task_queue,
                    execution_timeout=dt.timedelta(minutes=5),
                )

    assert "a 2026-10-28" in str(failure.value.cause)
    assert step_attempts == [("a", "2026-10-28", 1), ("a", "2026-10-27", 1), ("b", "2026-10-28", 1)]
    assert retention_tables == ["a", "b"]
