"""Tests for LLMAEvaluationSamplerWorkflow window derivation and input forwarding."""

import uuid
from datetime import datetime, timedelta

import pytest

from temporalio import activity
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from posthog.temporal.llm_analytics.evaluation_clustering.constants import (
    SAMPLER_WINDOW_MINUTES,
    SAMPLER_WINDOW_OFFSET_MINUTES,
)
from posthog.temporal.llm_analytics.evaluation_clustering.models import (
    SamplerActivityInputs,
    SamplerActivityResult,
    SamplerWorkflowInputs,
)
from posthog.temporal.llm_analytics.evaluation_clustering.workflow import LLMAEvaluationSamplerWorkflow


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
