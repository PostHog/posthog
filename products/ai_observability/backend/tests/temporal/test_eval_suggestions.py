import uuid
import logging
from collections.abc import Iterator

import pytest
from unittest.mock import patch

import temporalio
from temporalio import workflow
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.ai_observability.backend.temporal.eval_suggestions import (
    CoordinatorPlan,
    EvalSuggestionsCoordinatorWorkflow,
    EvalSuggestionsTeamWorkflow,
    FailRunInputs,
    StageInputs,
    StartRunInputs,
)
from products.ai_observability.backend.temporal.eval_suggestions_client import (
    COORDINATOR_WORKFLOW_NAME,
    TEAM_WORKFLOW_NAME,
    CoordinatorInputs,
    TeamRunInputs,
)

QUEUE = "eval-suggestions-test"


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
            task_queue=QUEUE,
            workflows=[EvalSuggestionsTeamWorkflow],
            activities=[start, fail],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            with pytest.raises(WorkflowFailureError):
                await env.client.execute_workflow(
                    TEAM_WORKFLOW_NAME,
                    TeamRunInputs(team_id=1, trigger="scheduled", include_paid=False),
                    id=str(uuid.uuid4()),
                    task_queue=QUEUE,
                )

    assert failed == started and len(started) == 1


@pytest.mark.asyncio
async def test_a_failed_paid_stage_still_publishes_the_free_cards(caplog: pytest.LogCaptureFixture) -> None:
    # The warning must really be emitted: a logger call the stdlib rejects would fail the workflow task.
    caplog.set_level(logging.WARNING)
    calls: list[str] = []

    @temporalio.activity.defn(name="llma-eval-suggestions-start-run")
    async def start(inputs: StartRunInputs) -> str:
        return inputs.run_id

    def stage(name: str, result: int = 0, error: bool = False):
        @temporalio.activity.defn(name=f"llma-eval-suggestions-{name}")
        async def run(inputs: StageInputs) -> int:
            calls.append(name)
            if error:
                raise ApplicationError("provider unavailable", non_retryable=True)
            return result

        return run

    @temporalio.activity.defn(name="llma-eval-suggestions-fail-run")
    async def fail(inputs: FailRunInputs) -> None:
        calls.append("fail-run")

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=QUEUE,
            workflows=[EvalSuggestionsTeamWorkflow],
            activities=[
                start,
                stage("measure"),
                stage("screen", error=True),
                stage("draft"),
                stage("publish", result=2),
                fail,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            published = await env.client.execute_workflow(
                TEAM_WORKFLOW_NAME,
                TeamRunInputs(team_id=1, trigger="scheduled", include_paid=True),
                id=str(uuid.uuid4()),
                task_queue=QUEUE,
            )

    assert published == 2
    assert calls == ["measure", "screen", "draft", "publish"]
    assert any(r.getMessage().startswith("eval_suggestions_paid_stage_failed") for r in caplog.records)


_SEEN: list[TeamRunInputs] = []


@workflow.defn(name=TEAM_WORKFLOW_NAME)
class RecordingTeamWorkflow:
    @workflow.run
    async def run(self, inputs: TeamRunInputs) -> int:
        _SEEN.append(inputs)
        return 0


@pytest.fixture
def _continue_as_new_once() -> Iterator[None]:
    """History looks too long on the first check only, so the coordinator hands its queue to a fresh run."""
    checks = iter([True])
    with patch.object(workflow.Info, "is_continue_as_new_suggested", lambda _info: next(checks, False)):
        yield


@pytest.mark.asyncio
@pytest.mark.usefixtures("_continue_as_new_once")
async def test_the_batch_id_survives_continue_as_new() -> None:
    _SEEN.clear()

    @temporalio.activity.defn(name="llma-eval-suggestions-plan")
    async def plan() -> CoordinatorPlan:
        return CoordinatorPlan(team_ids=[7, 8], max_concurrent_teams=1)

    workflow_id = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=QUEUE,
            workflows=[EvalSuggestionsCoordinatorWorkflow, RecordingTeamWorkflow],
            activities=[plan],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                COORDINATOR_WORKFLOW_NAME, CoordinatorInputs(), id=workflow_id, task_queue=QUEUE
            )

    # The budget is reserved per batch id, so a new id on the second leg would give each team its own budget.
    assert [(inputs.team_id, inputs.batch_id) for inputs in _SEEN] == [(7, workflow_id), (8, workflow_id)]
