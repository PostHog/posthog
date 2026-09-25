import uuid
import asyncio

import pytest

import temporalio.worker
from temporalio import activity
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from posthog.temporal.experiments.models import (
    ExperimentSavedMetricInput,
    ExperimentSavedMetricResult,
    ExperimentSavedMetricsWorkflowInputs,
)
from posthog.temporal.experiments.workflows import ExperimentSavedMetricsWorkflow

FAST_EXPERIMENT = 101
SLOW_EXPERIMENT = 102


async def _run_workflow(activities: list) -> dict:
    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ExperimentSavedMetricsWorkflow],
            activities=activities,
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            return await env.client.execute_workflow(
                ExperimentSavedMetricsWorkflow.run,
                ExperimentSavedMetricsWorkflowInputs(hour=2),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )


@pytest.mark.asyncio
async def test_an_experiment_publishes_before_the_whole_batch_finishes():
    """A slow experiment must not delay another experiment's publish. The slow experiment's metric only
    completes after the fast experiment's publish activity ran, so a workflow that publishes behind a
    whole-batch barrier fails this test (the fast publish then cannot run until the slow metric ends)."""
    fast_published = asyncio.Event()
    publish_calls: list[int] = []

    @activity.defn(name="get_experiment_saved_metrics_for_hour")
    async def mock_discover(hour: int) -> list[ExperimentSavedMetricInput]:
        return [
            ExperimentSavedMetricInput(
                experiment_id=FAST_EXPERIMENT, metric_uuid="m-fast", fingerprint="f1", team_id=1
            ),
            ExperimentSavedMetricInput(
                experiment_id=SLOW_EXPERIMENT, metric_uuid="m-slow", fingerprint="f2", team_id=1
            ),
        ]

    @activity.defn(name="calculate_experiment_saved_metric")
    async def mock_calculate(experiment_id: int, metric_uuid: str, fingerprint: str) -> ExperimentSavedMetricResult:
        if experiment_id == SLOW_EXPERIMENT:
            try:
                await asyncio.wait_for(fast_published.wait(), timeout=15)
            except TimeoutError:
                raise ApplicationError("the fast experiment never published", non_retryable=True)
        return ExperimentSavedMetricResult(
            experiment_id=experiment_id, metric_uuid=metric_uuid, fingerprint=fingerprint, success=True
        )

    @activity.defn(name="create_recalculation_from_timeseries")
    async def mock_publish(experiment_id: int, team_id: int, run_started_at: str) -> str | None:
        publish_calls.append(experiment_id)
        if experiment_id == FAST_EXPERIMENT:
            fast_published.set()
        return f"recalc-{experiment_id}"

    result = await _run_workflow([mock_discover, mock_calculate, mock_publish])

    assert publish_calls == [FAST_EXPERIMENT, SLOW_EXPERIMENT]
    assert result == {"hour": 2, "total": 2, "succeeded": 2, "failed": 0, "recalculations_synced": 2}


@pytest.mark.asyncio
async def test_publish_does_not_wait_in_the_metric_semaphore_queue():
    """Every metric task in the hour enqueues on the shared metric semaphore up front, and waiters are
    served in order. A publish that waited in that queue would sit behind the whole remaining batch. Here
    the batch saturates the ten metric slots and every slow metric only completes after the fast
    experiment's publish, so a queued-behind-metrics publish deadlocks and fails via the timeout guard."""
    fast_published = asyncio.Event()

    @activity.defn(name="get_experiment_saved_metrics_for_hour")
    async def mock_discover(hour: int) -> list[ExperimentSavedMetricInput]:
        slow = [
            ExperimentSavedMetricInput(
                experiment_id=SLOW_EXPERIMENT, metric_uuid=f"m-slow-{i}", fingerprint=f"s{i}", team_id=1
            )
            for i in range(14)
        ]
        return [
            ExperimentSavedMetricInput(
                experiment_id=FAST_EXPERIMENT, metric_uuid="m-fast", fingerprint="f1", team_id=1
            ),
            *slow,
        ]

    @activity.defn(name="calculate_experiment_saved_metric")
    async def mock_calculate(experiment_id: int, metric_uuid: str, fingerprint: str) -> ExperimentSavedMetricResult:
        if experiment_id == SLOW_EXPERIMENT:
            try:
                await asyncio.wait_for(fast_published.wait(), timeout=15)
            except TimeoutError:
                raise ApplicationError("the fast experiment never published", non_retryable=True)
        return ExperimentSavedMetricResult(
            experiment_id=experiment_id, metric_uuid=metric_uuid, fingerprint=fingerprint, success=True
        )

    @activity.defn(name="create_recalculation_from_timeseries")
    async def mock_publish(experiment_id: int, team_id: int, run_started_at: str) -> str | None:
        if experiment_id == FAST_EXPERIMENT:
            fast_published.set()
        return f"recalc-{experiment_id}"

    result = await _run_workflow([mock_discover, mock_calculate, mock_publish])

    assert result == {"hour": 2, "total": 15, "succeeded": 15, "failed": 0, "recalculations_synced": 2}
