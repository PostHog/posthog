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

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[ExperimentSavedMetricsWorkflow],
            activities=[mock_discover, mock_calculate, mock_publish],
            workflow_runner=temporalio.worker.UnsandboxedWorkflowRunner(),
        ):
            result = await env.client.execute_workflow(
                ExperimentSavedMetricsWorkflow.run,
                ExperimentSavedMetricsWorkflowInputs(hour=2),
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    assert publish_calls == [FAST_EXPERIMENT, SLOW_EXPERIMENT]
    assert result == {"hour": 2, "total": 2, "succeeded": 2, "failed": 0, "recalculations_synced": 2}
