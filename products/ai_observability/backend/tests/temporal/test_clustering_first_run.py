import logging
from dataclasses import asdict
from datetime import timedelta
from typing import Any

import pytest

from temporalio import activity, workflow
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.ai_observability.evaluation_clustering.models import SamplerWorkflowInputs
from posthog.temporal.ai_observability.trace_clustering.models import ClusteringWorkflowInputs
from posthog.temporal.ai_observability.trace_summarization.models import BatchSummarizationInputs

from products.ai_observability.backend.facade.clustering_contracts import (
    ClusteringRunContext,
    ClusteringRunRef,
    ClusteringRunUpdate,
)
from products.ai_observability.backend.temporal.clustering import ClusteringCountRequest, ClusteringFirstRunWorkflow


@pytest.fixture(autouse=True)
def log_temporal_at_info(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="temporalio.workflow")
    caplog.set_level(logging.INFO, logger="temporalio.activity")


@workflow.defn(name="llma-trace-summarization")
class PrepareTraces:
    @workflow.run
    async def run(self, value: BatchSummarizationInputs) -> None:
        await workflow.execute_activity(
            "record_first_preparation", asdict(value), start_to_close_timeout=timedelta(seconds=10)
        )


@workflow.defn(name="llma-evaluation-sampler")
class PrepareEvaluations:
    @workflow.run
    async def run(self, value: SamplerWorkflowInputs) -> None:
        await workflow.execute_activity(
            "record_first_preparation", asdict(value), start_to_close_timeout=timedelta(seconds=10)
        )


@workflow.defn(name="llma-trace-clustering")
class ClusterTraces:
    @workflow.run
    async def run(self, value: ClusteringWorkflowInputs) -> dict[str, Any]:
        count = await workflow.execute_activity(
            "record_first_clustering", asdict(value), start_to_close_timeout=timedelta(seconds=10)
        )
        return {"metrics": {"num_clusters": count, "total_items_analyzed": 10}}


@workflow.defn(name="llma-evaluation-clustering")
class ClusterEvaluations:
    @workflow.run
    async def run(self, value: SamplerWorkflowInputs) -> dict[str, int]:
        count = await workflow.execute_activity(
            "record_first_clustering", asdict(value), start_to_close_timeout=timedelta(seconds=10)
        )
        return {"embedded": count, "sampled": 10}


@pytest.mark.parametrize("level,initial_count,groups", [("trace", 0, 2), ("generation", 9, 2), ("evaluation", 9, 0)])
async def test_first_run_waits_for_enough_data_then_prepares_before_clustering(
    level: str, initial_count: int, groups: int
):
    updates: list[ClusteringRunUpdate] = []
    preparations: list[dict[str, Any]] = []
    samples = 0
    prepared_checks = 0
    ref = ClusteringRunRef(team_id=1, run_id="first-run")

    @activity.defn(name="clustering_run_context_activity")
    async def context(_: ClusteringRunRef) -> ClusteringRunContext:
        return ClusteringRunContext(
            active=True,
            job_id="job",
            job_name="Production",
            analysis_level=level,
            event_filters=[],
            minimum=10,
            lookback_days=3 if level == "evaluation" else 7,
        )

    @activity.defn(name="update_clustering_run_activity")
    async def update(value: ClusteringRunUpdate) -> None:
        updates.append(value)

    def eligible_count() -> int:
        nonlocal samples
        samples += 1
        return initial_count if samples == 1 else 10

    @activity.defn(name="sample_items_in_window_activity")
    async def sample(value: BatchSummarizationInputs) -> list[dict[str, str]]:
        assert value.max_items == 10 and value.job_id == "job"
        return [{"trace_id": str(i)} for i in range(eligible_count())]

    @activity.defn(name="clustering_count_activity")
    async def count(value: ClusteringCountRequest) -> int:
        nonlocal prepared_checks
        if not value.prepared:
            return eligible_count()
        prepared_checks += 1
        return 0 if prepared_checks == 1 else 10

    @activity.defn(name="record_first_preparation")
    async def prepare(value: dict[str, Any]) -> None:
        assert value["job_id"] == "job"
        assert value.get("max_items", value.get("max_samples")) == 100
        preparations.append(value)

    @activity.defn(name="record_first_clustering")
    async def cluster(value: dict[str, Any]) -> int:
        assert preparations and prepared_checks == 2
        assert value["job_id"] == "job" and value["max_samples"] == 100
        return groups

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="clustering-test",
            workflows=[
                ClusteringFirstRunWorkflow,
                PrepareTraces,
                PrepareEvaluations,
                ClusterTraces,
                ClusterEvaluations,
            ],
            activities=[context, update, sample, count, prepare, cluster],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                ClusteringFirstRunWorkflow.run,
                ref,
                id=f"first-{level}",
                task_queue="clustering-test",
                execution_timeout=timedelta(hours=3),
            )

    assert updates[0].status == "waiting" and updates[0].eligible_count == initial_count
    assert [update.status for update in updates] == [
        "waiting",
        "preparing",
        "preparing",
        "preparing",
        "clustering",
        "completed",
    ]
    assert updates[-1].cluster_count == groups
    assert len(preparations) == 1


@pytest.mark.parametrize("enabled", [False, True])
async def test_disabled_jobs_stop_and_query_failures_are_reported(enabled: bool):
    updates: list[ClusteringRunUpdate] = []

    @activity.defn(name="clustering_run_context_activity")
    async def context(_: ClusteringRunRef) -> ClusteringRunContext:
        return ClusteringRunContext(
            active=enabled,
            job_id="job",
            job_name="Traces",
            analysis_level="trace",
            event_filters=[],
            minimum=10,
            lookback_days=7,
        )

    @activity.defn(name="update_clustering_run_activity")
    async def update(value: ClusteringRunUpdate) -> None:
        updates.append(value)

    @activity.defn(name="sample_items_in_window_activity")
    async def sample(_: BatchSummarizationInputs) -> list:
        raise ApplicationError("query failed", non_retryable=True)

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue="failed-clustering-test",
            workflows=[ClusteringFirstRunWorkflow],
            activities=[context, update, sample],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            result = env.client.execute_workflow(
                ClusteringFirstRunWorkflow.run,
                ClusteringRunRef(team_id=1, run_id="failed"),
                id="failed",
                task_queue="failed-clustering-test",
                execution_timeout=timedelta(minutes=1),
            )
            if enabled:
                with pytest.raises(WorkflowFailureError):
                    await result
                assert len(updates) == 1
                assert updates[0].status == "failed" and updates[0].failure_reason == "processing_failed"
            else:
                await result
                assert updates == []
