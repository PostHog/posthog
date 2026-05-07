"""Tests for the evaluation sampler workflow window math and coordinator job filtering."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.llm_analytics.evaluation_clustering.constants import (
    SAMPLER_MAX_SAMPLES_PER_JOB,
    SAMPLER_WINDOW_MINUTES,
    SAMPLER_WINDOW_OFFSET_MINUTES,
)
from posthog.temporal.llm_analytics.evaluation_clustering.coordinator import _evaluation_jobs_for_team
from posthog.temporal.llm_analytics.evaluation_clustering.models import (
    SamplerActivityInputs,
    SamplerActivityResult,
    SamplerWorkflowInputs,
)
from posthog.temporal.llm_analytics.evaluation_clustering.workflow import LLMAEvaluationSamplerWorkflow
from posthog.temporal.llm_analytics.shared_activities import JobConfig


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
    """Run LLMAEvaluationSamplerWorkflow end-to-end with the sample activity mocked out.

    Returns the SamplerActivityInputs that the workflow dispatched, so callers can assert
    against the derived window, run_ts, and forwarded fields without touching ClickHouse.
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
            workflows=[LLMAEvaluationSamplerWorkflow],
            activities=[mock_activity],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            await env.client.execute_workflow(
                LLMAEvaluationSamplerWorkflow.run,
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

        Pins on workflow.run_ts (stamped from the same workflow.now() call) so the
        assertion is independent of wall-clock time, and asserts against the offset
        and window constants directly so a future accidental swap is caught.
        """
        inputs = SamplerWorkflowInputs(team_id=7, job_id="j-derived", job_name="derived window")

        activity_inputs = await _run_sampler_with_mock_activity(inputs)

        run_ts = _parse_z(activity_inputs.run_ts)
        window_end = _parse_z(activity_inputs.window_end)
        window_start = _parse_z(activity_inputs.window_start)

        assert window_end == run_ts - timedelta(minutes=SAMPLER_WINDOW_OFFSET_MINUTES)
        assert window_start == window_end - timedelta(minutes=SAMPLER_WINDOW_MINUTES)

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
