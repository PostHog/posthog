"""Tests for the evaluation sampler workflow window math and coordinator job filtering."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import patch

from parameterized import parameterized
from temporalio import activity, workflow
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.ai_observability.evaluation_clustering.activities import (
    EvaluationClusteringComputeInputs,
    EvaluationClusteringComputeResult,
    FetchEvaluationMetadataResult,
    GenerateEvaluationLabelsInputs,
    GenerateEvaluationLabelsOutputs,
    _compute_sync,
)
from posthog.temporal.ai_observability.evaluation_clustering.constants import (
    SAMPLER_MAX_SAMPLES_PER_JOB,
    SAMPLER_WINDOW_MINUTES,
    SAMPLER_WINDOW_OFFSET_MINUTES,
    SAMPLER_WORKFLOW_NAME,
)
from posthog.temporal.ai_observability.evaluation_clustering.coordinator import (
    AIObservabilityEvaluationSamplerCoordinatorWorkflow,
    SamplerCoordinatorInputs,
    _evaluation_jobs_for_team,
)
from posthog.temporal.ai_observability.evaluation_clustering.models import (
    SamplerActivityInputs,
    SamplerActivityResult,
    SamplerWorkflowInputs,
    SamplerWorkflowResult,
)
from posthog.temporal.ai_observability.evaluation_clustering.workflow import (
    AIObservabilityEvaluationClusteringWorkflow,
    AIObservabilityEvaluationSamplerWorkflow,
)
from posthog.temporal.ai_observability.shared_activities import FetchAllClusteringJobsInput, JobConfig
from posthog.temporal.ai_observability.team_discovery import TeamDiscoveryInput
from posthog.temporal.ai_observability.trace_clustering.models import ClusteringMetrics, ClusteringResult, ClusterLabel


class TestEvaluationJobsForTeam:
    def test_picks_only_evaluation_level_jobs(self):
        jobs = [
            JobConfig(job_id="j1", name="Trace", analysis_level="trace", event_filters=[]),
            JobConfig(job_id="j2", name="Gen", analysis_level="generation", event_filters=[]),
            JobConfig(job_id="j3", name="Eval", analysis_level="evaluation", event_filters=[]),
            JobConfig(job_id="j4", name="Eval2", analysis_level="evaluation", event_filters=[{"key": "x"}]),
        ]
        result = _evaluation_jobs_for_team(jobs)
        assert [j.job_id for j in result] == ["j3", "j4"]

    def test_no_evaluation_jobs_returns_empty(self):
        jobs = [
            JobConfig(job_id="j1", name="Trace", analysis_level="trace", event_filters=[]),
        ]
        assert _evaluation_jobs_for_team(jobs) == []

    def test_empty_input_returns_empty(self):
        assert _evaluation_jobs_for_team([]) == []


class TestWindowMathFormula:
    """Pure formula sanity check — no workflow runtime, just the arithmetic.

    The workflow code does:
        window_end   = now - OFFSET
        window_start = window_end - WINDOW
    """

    def test_window_matches_spec(self):
        now = datetime(2026, 4, 15, 12, 0, 0, tzinfo=UTC)
        expected_end = now - timedelta(minutes=SAMPLER_WINDOW_OFFSET_MINUTES)
        expected_start = expected_end - timedelta(minutes=SAMPLER_WINDOW_MINUTES)

        # Window is 1h, offset is 30min — so [11:30 - 30, 11:30)
        assert expected_end == datetime(2026, 4, 15, 11, 30, 0, tzinfo=UTC)
        assert expected_start == datetime(2026, 4, 15, 10, 30, 0, tzinfo=UTC)

    def test_sample_cap_is_250(self):
        # Locked in the spec — warn loudly if someone changes this without updating Stage B's
        # assumptions about daily accumulation volume.
        assert SAMPLER_MAX_SAMPLES_PER_JOB == 250


def _parse_z(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


async def _run_sampler_with_mock_activity(
    inputs: SamplerWorkflowInputs,
) -> SamplerActivityInputs:
    """Run AIObservabilityEvaluationSamplerWorkflow end-to-end with the sample activity mocked out.

    Returns the SamplerActivityInputs that the workflow dispatched, so callers can assert
    against the derived window and forwarded fields without touching ClickHouse.
    """
    captured: dict[str, SamplerActivityInputs] = {}

    @activity.defn(name="sample_and_embed_for_job_activity")
    async def mock_activity(activity_inputs: SamplerActivityInputs) -> SamplerActivityResult:
        captured["inputs"] = activity_inputs
        return SamplerActivityResult(
            team_id=activity_inputs.team_id,
            job_id=activity_inputs.job_id,
            sampled=0,
            embedded=0,
        )

    task_queue = str(uuid.uuid4())
    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=task_queue,
            workflows=[AIObservabilityEvaluationSamplerWorkflow],
            activities=[mock_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                AIObservabilityEvaluationSamplerWorkflow.run,
                inputs,
                id=str(uuid.uuid4()),
                task_queue=task_queue,
            )

    return captured["inputs"]


class TestSamplerWorkflowWindowMath:
    """End-to-end verification — runs the workflow in WorkflowEnvironment.start_time_skipping()
    with a mocked activity, so the formula test above still catches regressions even if the
    workflow wiring changes shape.
    """

    @pytest.mark.asyncio
    async def test_derives_window_from_workflow_now(self):
        """When window_start/window_end are not supplied, the workflow derives them.

        Contract under test (workflow.py:run):
            window_end   = workflow.now() - SAMPLER_WINDOW_OFFSET_MINUTES
            window_start = window_end     - SAMPLER_WINDOW_MINUTES

        Asserts the derived window spans exactly SAMPLER_WINDOW_MINUTES; the absolute offset
        from workflow.now() is pinned separately by TestWindowMathFormula. (Independent of
        wall-clock because it only checks the span between the two derived bounds.)
        """
        inputs = SamplerWorkflowInputs(team_id=7, job_id="j-derived", job_name="derived window")

        activity_inputs = await _run_sampler_with_mock_activity(inputs)

        window_end = _parse_z(activity_inputs.window_end)
        window_start = _parse_z(activity_inputs.window_start)

        assert window_end - window_start == timedelta(minutes=SAMPLER_WINDOW_MINUTES)

    @pytest.mark.asyncio
    async def test_honours_explicit_window_override(self):
        """When window_start/window_end are supplied (e.g. for replay), the workflow passes them through untouched."""
        explicit_start = "2026-04-01T00:00:00Z"
        explicit_end = "2026-04-01T01:00:00Z"
        inputs = SamplerWorkflowInputs(
            team_id=7,
            job_id="j-override",
            job_name="explicit window",
            window_start=explicit_start,
            window_end=explicit_end,
        )

        activity_inputs = await _run_sampler_with_mock_activity(inputs)

        assert activity_inputs.window_start == explicit_start
        assert activity_inputs.window_end == explicit_end

    @pytest.mark.asyncio
    async def test_forwards_team_and_filters_to_activity(self):
        """Team id, job metadata, and event_filters are forwarded to the activity unchanged."""
        filters = [{"key": "$ai_evaluation_name", "value": "Relevance", "operator": "exact", "type": "event"}]
        inputs = SamplerWorkflowInputs(
            team_id=42,
            job_id="j-forward",
            job_name="forward test",
            event_filters=filters,
        )

        activity_inputs = await _run_sampler_with_mock_activity(inputs)

        assert activity_inputs.team_id == 42
        assert activity_inputs.job_id == "j-forward"
        assert activity_inputs.job_name == "forward test"
        assert activity_inputs.event_filters == filters


sampler_child_windows: list[tuple[str, str]] = []
sampler_discovery_inputs: list[TeamDiscoveryInput | None] = []


@workflow.defn(name=SAMPLER_WORKFLOW_NAME)
class FakeEvaluationSamplerWorkflow:
    @workflow.run
    async def run(self, inputs: SamplerWorkflowInputs) -> SamplerWorkflowResult:
        if not workflow.unsafe.is_replaying():
            sampler_child_windows.append((inputs.window_start or "", inputs.window_end or ""))
        # A later continue_as_new leg then starts minutes after the first, so it would derive a different window.
        await workflow.sleep(timedelta(minutes=10))
        return SamplerWorkflowResult(
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            sampled=0,
            embedded=0,
            window_start=inputs.window_start or "",
            window_end=inputs.window_end or "",
        )


@activity.defn(name="get_team_ids_for_llm_analytics")
async def fake_eval_team_discovery(inputs: TeamDiscoveryInput | None = None) -> list[int]:
    sampler_discovery_inputs.append(inputs)
    return [1, 2]


@activity.defn(name="fetch_all_clustering_jobs_activity")
async def fake_fetch_eval_jobs(inputs: FetchAllClusteringJobsInput) -> dict[int, list[JobConfig]]:
    return {
        team_id: [JobConfig(job_id=f"j{team_id}", name="evals", analysis_level="evaluation", event_filters=[])]
        for team_id in inputs.team_ids
    }


class TestSamplerCoordinatorWindow:
    @parameterized.expand([("single_leg", False), ("continue_as_new_each_batch", True)])
    @pytest.mark.asyncio
    async def test_children_sample_the_window_discovery_checked(self, _name, continue_as_new):
        sampler_child_windows.clear()
        sampler_discovery_inputs.clear()
        task_queue = str(uuid.uuid4())
        with patch.object(workflow.Info, "is_continue_as_new_suggested", return_value=continue_as_new):
            async with await WorkflowEnvironment.start_time_skipping() as env:
                async with Worker(
                    env.client,
                    task_queue=task_queue,
                    workflows=[AIObservabilityEvaluationSamplerCoordinatorWorkflow, FakeEvaluationSamplerWorkflow],
                    activities=[fake_eval_team_discovery, fake_fetch_eval_jobs],
                    workflow_runner=UnsandboxedWorkflowRunner(),
                ):
                    await env.client.execute_workflow(
                        AIObservabilityEvaluationSamplerCoordinatorWorkflow.run,
                        SamplerCoordinatorInputs(max_concurrent_teams=1),
                        id=str(uuid.uuid4()),
                        task_queue=task_queue,
                    )

        assert len(sampler_child_windows) == 2
        windows = set(sampler_child_windows)
        assert len(windows) == 1
        window_start, window_end = next(iter(windows))
        assert _parse_z(window_end) - _parse_z(window_start) == timedelta(minutes=SAMPLER_WINDOW_MINUTES)
        assert sampler_discovery_inputs == [
            TeamDiscoveryInput(window_start=window_start, window_end=window_end, trigger_events=["$ai_evaluation"])
        ]


class TestClusteringWorkflowWiring:
    @pytest.mark.asyncio
    async def test_forwards_workflow_run_identity_to_labeling(self) -> None:
        trace_uuid = uuid.UUID("11111111-1111-4111-8111-111111111111")
        compute_result = EvaluationClusteringComputeResult(
            clustering_run_id="1_evaluation_20250108_000000_job-1",
            eval_ids=["evaluation-1"],
            labels=[0],
            centroids=[[0.0, 0.0]],
            distances=[[0.0]],
            coords_2d=[[0.0, 0.0]],
            centroid_coords_2d=[[0.0, 0.0]],
        )
        emitted_result = ClusteringResult(
            clustering_run_id=compute_result.clustering_run_id,
            team_id=1,
            timestamp="2025-01-08T00:00:00+00:00",
            window_start="2025-01-01T00:00:00+00:00",
            window_end="2025-01-08T00:00:00+00:00",
            metrics=ClusteringMetrics(total_items_analyzed=1, num_clusters=1, duration_seconds=1.0),
            clusters=[],
        )
        activity_inputs: list[object] = []
        responses = iter(
            [
                compute_result,
                FetchEvaluationMetadataResult(metadata={}),
                GenerateEvaluationLabelsOutputs(
                    cluster_labels={0: ClusterLabel(title="Cluster", description="Description")}
                ),
                {},
                emitted_result,
            ]
        )

        async def fake_execute_activity(_activity: object, inputs: object, **_kwargs: object) -> object:
            activity_inputs.append(inputs)
            return next(responses)

        with (
            patch(
                "posthog.temporal.ai_observability.evaluation_clustering.workflow.workflow.execute_activity",
                new=fake_execute_activity,
            ),
            patch(
                "posthog.temporal.ai_observability.evaluation_clustering.workflow.workflow.now",
                return_value=datetime(2025, 1, 8, tzinfo=UTC),
            ),
            patch(
                "posthog.temporal.ai_observability.evaluation_clustering.workflow.workflow.uuid4",
                return_value=trace_uuid,
            ),
            patch("posthog.temporal.ai_observability.evaluation_clustering.workflow.record_items_analyzed"),
            patch("posthog.temporal.ai_observability.evaluation_clustering.workflow.record_noise_points"),
            patch("posthog.temporal.ai_observability.evaluation_clustering.workflow.record_clusters_generated"),
        ):
            await AIObservabilityEvaluationClusteringWorkflow().run(
                SamplerWorkflowInputs(team_id=1, job_id="job-1", job_name="Job 1")
            )

        label_inputs = activity_inputs[2]
        assert isinstance(label_inputs, GenerateEvaluationLabelsInputs)
        assert label_inputs.trace_id == str(trace_uuid)
        assert label_inputs.session_id == f"{trace_uuid}:session"
        assert label_inputs.clustering_run_id == compute_result.clustering_run_id
        assert label_inputs.clustering_job_id == "job-1"
        assert label_inputs.properties_to_log == {
            "team_id": 1,
            "trace_id": str(trace_uuid),
            "session_id": f"{trace_uuid}:session",
            "clustering_run_id": compute_result.clustering_run_id,
            "clustering_job_id": "job-1",
        }


@pytest.mark.django_db
def test_compute_skips_deleted_team() -> None:
    result = _compute_sync(EvaluationClusteringComputeInputs(team_id=999_999_999, job_id="job-1", job_name="job"))

    assert result.skip_reason == "team_not_found"
    assert result.eval_ids == []
