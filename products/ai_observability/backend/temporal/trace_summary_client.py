from django.conf import settings

from asgiref.sync import async_to_sync
from temporalio.client import Client
from temporalio.common import RetryPolicy, WorkflowIDConflictPolicy

from posthog.temporal.common.client import async_connect

from ..facade.contracts import TraceSummaryJob
from ..logic.traces.summary import WORKFLOW_DEADLINE, workflow_id

TRACE_SUMMARY_WORKFLOW_NAME = "ai-observability-trace-summary"


async def start_trace_summary_workflow(client: Client, job: TraceSummaryJob) -> str | None:
    """Start the job's workflow, or attach to the run already writing this summary. Returns the run id."""
    handle = await client.start_workflow(
        TRACE_SUMMARY_WORKFLOW_NAME,
        job,
        id=workflow_id(job),
        task_queue=settings.LLMA_TASK_QUEUE,
        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
        execution_timeout=WORKFLOW_DEADLINE,
        retry_policy=RetryPolicy(maximum_attempts=1),
    )
    return handle.result_run_id


def start_trace_summary(job: TraceSummaryJob) -> None:
    async def start() -> None:
        await start_trace_summary_workflow(await async_connect(), job)

    async_to_sync(start)()
