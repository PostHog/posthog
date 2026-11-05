import asyncio
import logging
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from unittest.mock import MagicMock, patch

from django.conf import settings

from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment, WorkflowEnvironment
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

from products.ai_observability.backend.facade.contracts import TraceSummaryJob, TraceSummaryRun
from products.ai_observability.backend.logic.traces.summary import TraceSummaryRetryableError, workflow_id
from products.ai_observability.backend.temporal import trace_summary
from products.ai_observability.backend.temporal.trace_summary import (
    FAIL_TRACE_SUMMARY_ACTIVITY_NAME,
    GENERATE_TRACE_SUMMARY_ACTIVITY_NAME,
    TraceSummaryWorkflow,
    generate_trace_summary_activity,
)
from products.ai_observability.backend.temporal.trace_summary_client import start_trace_summary_workflow

JOB = TraceSummaryJob(
    team_id=1,
    trace_id="trace-1",
    timestamp_hint=datetime(2026, 9, 1, 10, 0, tzinfo=UTC),
    fingerprint="f",
    requester_id=7,
    requested_at=datetime(2026, 9, 1, 10, 5, tzinfo=UTC),
)
FAILED_RUN = TraceSummaryRun(
    status="failed",
    failure_reason="provider_error",
    duration_ms=1200,
    input_characters=5000,
    model="gpt-4.1-mini",
    was_sampled=False,
    distinct_id="user-7",
    groups={"organization": "org-1"},
)


@pytest.fixture(autouse=True)
def temporal_loggers_at_info() -> Iterator[None]:
    # A logging call with fields the stdlib logger rejects raises only at INFO, and then wedges the workflow.
    loggers = [logging.getLogger("temporalio.activity"), logging.getLogger("temporalio.workflow")]
    levels = [logger.level for logger in loggers]
    for logger in loggers:
        logger.setLevel(logging.INFO)
    yield
    for logger, level in zip(loggers, levels):
        logger.setLevel(level)


async def test_two_requests_while_a_job_runs_share_one_run() -> None:
    received: list[TraceSummaryJob] = []
    release = asyncio.Event()

    @activity.defn(name=GENERATE_TRACE_SUMMARY_ACTIVITY_NAME)
    async def fake_generate(job: TraceSummaryJob) -> None:
        received.append(job)
        await release.wait()

    @activity.defn(name=FAIL_TRACE_SUMMARY_ACTIVITY_NAME)
    async def fake_fail(job: TraceSummaryJob) -> None:
        raise AssertionError("a finished job must not be marked failed")

    async with await WorkflowEnvironment.start_time_skipping() as env:
        async with Worker(
            env.client,
            task_queue=settings.LLMA_TASK_QUEUE,
            workflows=[TraceSummaryWorkflow],
            activities=[fake_generate, fake_fail],
            workflow_runner=UnsandboxedWorkflowRunner(),
        ):
            first = await start_trace_summary_workflow(env.client, JOB)
            second = await start_trace_summary_workflow(env.client, JOB)
            release.set()
            await env.client.get_workflow_handle(workflow_id(JOB)).result()

    assert first is not None and first == second
    assert received == [JOB]


async def test_a_job_that_ends_without_a_result_marks_its_summary_failed() -> None:
    attempts: list[TraceSummaryJob] = []
    abandoned: list[TraceSummaryJob] = []

    @activity.defn(name=GENERATE_TRACE_SUMMARY_ACTIVITY_NAME)
    async def broken_generate(job: TraceSummaryJob) -> None:
        attempts.append(job)
        raise ApplicationError("boom", type="TypeError")

    @activity.defn(name=FAIL_TRACE_SUMMARY_ACTIVITY_NAME)
    async def record_fail(job: TraceSummaryJob) -> None:
        abandoned.append(job)

    # The test server does not skip the backoff between activity attempts.
    with patch.object(trace_summary, "RETRY_INITIAL_INTERVAL", timedelta(milliseconds=10)):
        async with await WorkflowEnvironment.start_time_skipping() as env:
            async with Worker(
                env.client,
                task_queue=settings.LLMA_TASK_QUEUE,
                workflows=[TraceSummaryWorkflow],
                activities=[broken_generate, record_fail],
                workflow_runner=UnsandboxedWorkflowRunner(),
            ):
                await start_trace_summary_workflow(env.client, JOB)
                with pytest.raises(WorkflowFailureError):
                    await env.client.get_workflow_handle(workflow_id(JOB)).result()

    assert len(attempts) == 2
    assert abandoned == [JOB]


async def test_activity_reports_a_finished_run() -> None:
    capture = MagicMock()
    with (
        patch.object(trace_summary.api, "generate_trace_summary", return_value=FAILED_RUN),
        patch.object(trace_summary, "ph_background_capture", return_value=capture),
    ):
        await ActivityEnvironment().run(generate_trace_summary_activity, JOB)

    capture.assert_called_once()
    kwargs = capture.call_args.kwargs
    assert (kwargs["event"], kwargs["distinct_id"]) == ("llma trace view summary failed", "user-7")
    assert kwargs["groups"] == {"organization": "org-1"}
    assert kwargs["properties"]["failure_reason"] == "provider_error"


async def test_activity_leaves_a_retryable_failure_to_temporal() -> None:
    capture = MagicMock()
    with (
        patch.object(
            trace_summary.api, "generate_trace_summary", side_effect=TraceSummaryRetryableError("provider_error")
        ),
        patch.object(trace_summary, "ph_background_capture", return_value=capture),
        pytest.raises(TraceSummaryRetryableError),
    ):
        await ActivityEnvironment().run(generate_trace_summary_activity, JOB)

    capture.assert_not_called()
