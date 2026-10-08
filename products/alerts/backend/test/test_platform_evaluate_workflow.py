import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.alerts.backend.temporal.platform_evaluate import (
    EVALUATION_BUDGET,
    InsightAlertPlatformEvaluateWorkflow,
    InsightBatchPlanInputs,
    InsightCheckInputs,
)
from products.alerts_platform.backend.facade.contracts import (
    RECORD_OUTCOMES_ACTIVITY,
    AlertBatchKey,
    AlertEventKind,
    PlatformAlertOutcome,
    SourceEvaluationInputs,
    SourceKind,
    SourceOutcomeInputs,
)
from products.alerts_platform.backend.facade.temporal import source_evaluation_timeout

QUEUE = "test-platform-insight-evaluation"
ADMITTED = ("00000000-0000-0000-0000-000000000001", "00000000-0000-0000-0000-000000000002")


@pytest_asyncio.fixture
async def environment() -> AsyncIterator[WorkflowEnvironment]:
    async with await WorkflowEnvironment.start_time_skipping() as env:
        yield env


async def test_a_check_that_fails_does_not_stop_the_batch_recording_the_rest(environment: WorkflowEnvironment) -> None:
    recorded: list[SourceOutcomeInputs] = []

    @activity.defn(name="plan_platform_insight_batch_activity")
    async def plan(inputs: InsightBatchPlanInputs) -> list[str]:
        return list(ADMITTED)

    @activity.defn(name="evaluate_platform_insight_check_activity")
    async def evaluate(inputs: InsightCheckInputs) -> PlatformAlertOutcome | None:
        if inputs.configuration_id == ADMITTED[0]:
            raise ApplicationError("query failed", non_retryable=True)
        return PlatformAlertOutcome(
            configuration_id=uuid.UUID(inputs.configuration_id),
            evaluation_key="slot:2026-09-16T10:00:00+00:00",
            kind=AlertEventKind.CHECK,
            new_state="not_firing",
            notified=False,
            consecutive_failures=0,
        )

    @activity.defn(name=RECORD_OUTCOMES_ACTIVITY)
    async def record(inputs: SourceOutcomeInputs) -> int:
        recorded.append(inputs)
        return len(inputs.outcomes)

    async with Worker(
        environment.client,
        task_queue=QUEUE,
        workflows=[InsightAlertPlatformEvaluateWorkflow],
        activities=[plan, evaluate, record],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        result = await environment.client.execute_workflow(
            InsightAlertPlatformEvaluateWorkflow.run,
            SourceEvaluationInputs(
                source=SourceKind.INSIGHT,
                cutoff="2026-09-16T10:00:00+00:00",
                batch_key=AlertBatchKey(team_id=1, slot="2026-09-16T10:00:00+00:00"),
            ),
            id=f"test-{uuid.uuid4()}",
            task_queue=QUEUE,
        )

    assert result == 1
    assert [[str(o.configuration_id) for o in batch.outcomes] for batch in recorded] == [[ADMITTED[1]]]


def test_the_binding_holds_the_whole_batch() -> None:
    assert source_evaluation_timeout(SourceKind.INSIGHT) > EVALUATION_BUDGET
