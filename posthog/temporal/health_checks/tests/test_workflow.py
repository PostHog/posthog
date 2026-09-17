import uuid
import logging
import dataclasses
from collections import Counter
from datetime import timedelta

import pytest

from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.health_checks.models import BatchResult, HealthCheckWorkflowInputs
from posthog.temporal.health_checks.registry import HealthCheckKindNotRegistered
from posthog.temporal.health_checks.workflows import HealthCheckWorkflow

UNREGISTERED_KIND = "not_in_this_image"

# Temporal activity stubs cannot carry per-test state, so the calls they record live here.
_CALLS: Counter[str] = Counter()


@activity.defn(name="get_team_id_batches")
async def stub_get_team_id_batches(inputs: HealthCheckWorkflowInputs) -> list[list[int]]:
    _CALLS["batches"] += 1
    if inputs.kind == UNREGISTERED_KIND:
        raise HealthCheckKindNotRegistered(f"Health check kind '{inputs.kind}' has no detect function")
    return [[1, 2], [3]]


@activity.defn(name="run_health_check_batch")
async def stub_run_health_check_batch(team_ids: list[int], kind: str, dry_run: bool) -> dict:
    _CALLS["run_batch"] += 1
    return dataclasses.asdict(BatchResult(batch_size=len(team_ids), teams_healthy=len(team_ids)))


@activity.defn(name="push_health_check_metrics_activity")
async def stub_push_health_check_metrics(kind: str, totals_dict: dict, success: bool) -> None:
    _CALLS["metrics"] += 1


async def _run_workflow(kind: str) -> dict:
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[HealthCheckWorkflow],
            activities=[
                stub_get_team_id_batches,
                stub_run_health_check_batch,
                stub_push_health_check_metrics,
            ],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            return await env.client.execute_workflow(
                HealthCheckWorkflow.run,
                HealthCheckWorkflowInputs(name="Stub check", kind=kind),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
                execution_timeout=timedelta(minutes=2),
            )


class TestHealthCheckWorkflow:
    @pytest.fixture(autouse=True)
    def _isolate(self, caplog: pytest.LogCaptureFixture) -> None:
        # The Temporal loggers reject structured keyword fields, but only once the level
        # lets the record through. Production runs at INFO, so the tests do too.
        caplog.set_level(logging.INFO, logger="temporalio.activity")
        caplog.set_level(logging.INFO, logger="temporalio.workflow")
        _CALLS.clear()

    @pytest.mark.asyncio
    async def test_unregistered_kind_fails_once_without_fanning_out(self) -> None:
        with pytest.raises(WorkflowFailureError):
            await _run_workflow(UNREGISTERED_KIND)

        assert _CALLS["batches"] == 1
        assert "run_batch" not in _CALLS

    @pytest.mark.asyncio
    async def test_registered_kind_runs_every_batch(self) -> None:
        result = await _run_workflow("stub_check")

        assert _CALLS["run_batch"] == 2
        assert _CALLS["metrics"] == 1
        assert result["total_teams"] == 3
        assert result["teams_healthy"] == 3
