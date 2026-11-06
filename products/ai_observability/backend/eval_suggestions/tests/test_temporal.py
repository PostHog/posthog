import uuid

import pytest

import temporalio
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.ai_observability.backend.eval_suggestions.client import TEAM_WORKFLOW_NAME, TeamRunInputs
from products.ai_observability.backend.eval_suggestions.temporal import (
    EvalSuggestionsTeamWorkflow,
    FailRunInputs,
    StartRunInputs,
)


@pytest.mark.asyncio
async def test_a_start_that_never_returns_still_fails_its_run() -> None:
    started: list[str] = []
    failed: list[str] = []

    @temporalio.activity.defn(name="llma-eval-suggestions-start-run")
    async def start(inputs: StartRunInputs) -> str:
        # The row exists, but the worker gives up before Temporal records the result.
        started.append(inputs.run_id)
        raise ApplicationError("worker lost", non_retryable=True)

    @temporalio.activity.defn(name="llma-eval-suggestions-fail-run")
    async def fail(inputs: FailRunInputs) -> None:
        failed.append(inputs.run_id)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="eval-suggestions-test",
            workflows=[EvalSuggestionsTeamWorkflow],
            activities=[start, fail],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await env.client.execute_workflow(
                    TEAM_WORKFLOW_NAME,
                    TeamRunInputs(team_id=1, trigger="scheduled", include_paid=False),
                    id=str(uuid.uuid4()),
                    task_queue="eval-suggestions-test",
                )

    assert failed == started and len(started) == 1
