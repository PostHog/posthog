import asyncio
from collections.abc import Generator
from dataclasses import dataclass
import dataclasses
from datetime import timedelta
import json
import time
import uuid
import temporalio
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from django.conf import settings
from ee.hogai.utils.asgi import SyncIterableToAsync
from ee.session_recordings.session_summary.llm.consume import stream_llm_session_summary
from ee.session_recordings.session_summary.summarize_session import (
    ExtraSummaryContext,
    prepare_data_for_single_session_summary,
)
from posthog.models.team.team import Team
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import connect
from posthog.settings import SERVER_GATEWAY_INTERFACE
from temporalio.client import Client as TemporalClient, WorkflowHandle, WorkflowExecutionDescription
from temporalio.activity import info as workflow_info


async def _connect_to_temporal_client() -> TemporalClient:
    return await connect(
        settings.TEMPORAL_HOST,
        settings.TEMPORAL_PORT,
        settings.TEMPORAL_NAMESPACE,
        server_root_ca_cert=settings.TEMPORAL_CLIENT_ROOT_CA,
    )


@dataclass(frozen=True, kw_only=True)
class SessionSummaryInputs:
    session_id: str
    user_pk: int
    summary_prompt: str
    system_prompt: str
    simplified_events_mapping: dict[str, list[str | int | None | list[str]]]
    simplified_events_columns: list[str]
    url_mapping_reversed: dict[str, str]
    window_mapping_reversed: dict[str, str]
    session_start_time_str: str
    session_duration: int


@temporalio.activity.defn
async def stream_llm_summary_activity(inputs: SessionSummaryInputs) -> str:
    latest_summary_state = ""
    session_summary_generator = stream_llm_session_summary(
        session_id=inputs.session_id,
        user_pk=inputs.user_pk,
        summary_prompt=inputs.summary_prompt,
        system_prompt=inputs.system_prompt,
        allowed_event_ids=list(inputs.simplified_events_mapping.keys()),
        simplified_events_mapping=inputs.simplified_events_mapping,
        simplified_events_columns=inputs.simplified_events_columns,
        url_mapping_reversed=inputs.url_mapping_reversed,
        window_mapping_reversed=inputs.window_mapping_reversed,
        session_start_time_str=inputs.session_start_time_str,
        session_duration=inputs.session_duration,
    )
    info = workflow_info()
    client = await _connect_to_temporal_client()
    handle = await client.get_workflow_handle(worklfow_id=info.workflow_id, run_id=info.run_id)
    await handle.update_latest_summary_state(latest_summary_state)
    # Iterate the async generator, store chunks, and return the combined result
    async for state in session_summary_generator:
        latest_summary_state = state
        # Send update to workflow instead of heartbeat
        await handle.execute_update(SummarizeSessionWorkflow.update_latest_summary_state, latest_summary_state)
    return latest_summary_state


@temporalio.workflow.defn(name="summarize-session")
class SummarizeSessionWorkflow(PostHogWorkflow):
    def __init__(self):
        self.summary_state: str = ""

    @temporalio.workflow.query
    def get_latest_summary_state(self) -> str:
        """Query to get the current accumulated summary."""
        return self.summary_state

    @temporalio.workflow.update
    async def update_latest_summary_state(self, latest_summary_state: str) -> None:
        """Update handler to set current accumulated summary as the latest summary state"""
        self.summary_state = latest_summary_state

    @staticmethod
    def parse_inputs(inputs: list[str]) -> None:
        try:
            parsed_inputs = json.loads(inputs[0])
            return SessionSummaryInputs(**parsed_inputs)
        except Exception as e:
            raise ValueError(f"Failed to parse inputs: {e}") from e

    @temporalio.workflow.run
    async def run(self, inputs: list[str]) -> str:
        parsed_inputs = self.parse_inputs(inputs)
        # Run as activity with heartbeat timeout
        result = await temporalio.workflow.execute_activity(
            stream_llm_summary_activity,
            parsed_inputs,
            start_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return result


async def _start_workflow(str_inputs: list[str], workflow_id: str) -> WorkflowHandle:
    client = await _connect_to_temporal_client()
    retry_policy = RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS))
    handle = await client.start_workflow(
        "summarize-session",
        str_inputs,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        retry_policy=retry_policy,
    )
    return handle


async def _query_workflow_state(handle: WorkflowHandle) -> tuple[str, WorkflowExecutionDescription]:
    current_summary = await handle.query(SummarizeSessionWorkflow.get_latest_summary_state)
    desc = await handle.describe()
    return current_summary, desc


def excectute_test_summarize_session(
    session_id: str,
    user_pk: int,
    team: Team,
    extra_summary_context: ExtraSummaryContext | None = None,
    local_reads_prod: bool = False,
) -> Generator[str, None, None]:
    """
    Start the workflow and yield chunks as they become available, polling the get_chunks query.
    This is a sync generator.
    """
    # Collect data required for the workflow to generate the summary for a single session
    summary_data = prepare_data_for_single_session_summary(
        session_id=session_id,
        user_pk=user_pk,
        team=team,
        extra_summary_context=extra_summary_context,
        local_reads_prod=local_reads_prod,
    )
    if summary_data.sse_error_msg is not None or summary_data.prompt_data is None or summary_data.prompt is None:
        # If we weren't able to collect the required data, return the error message right away
        return summary_data.sse_error_msg
    # Checking here instead of in the preparation function to keep mypy happy
    if summary_data.prompt_data.prompt_data.metadata.start_time is None:
        raise ValueError(f"Session start time is missing in the session metadata for session_id {session_id}")
    if summary_data.prompt_data.prompt_data.metadata.duration is None:
        raise ValueError(f"Session duration is missing in the session metadata for session_id {session_id}")
    # Connect to the client and prepare the input
    # TODO: Generate a proper id
    random_id = str(uuid.uuid4())
    session_start_time_str = summary_data.prompt_data.prompt_data.metadata.start_time.isoformat()
    # TODO: Store in Redis and send a key instead
    inputs = SessionSummaryInputs(
        session_id=session_id,
        user_pk=user_pk,
        summary_prompt=summary_data.prompt.summary_prompt,
        system_prompt=summary_data.prompt.system_prompt,
        simplified_events_mapping=summary_data.prompt_data.simplified_events_mapping,
        simplified_events_columns=summary_data.prompt_data.prompt_data.columns,
        url_mapping_reversed=summary_data.prompt_data.url_mapping_reversed,
        window_mapping_reversed=summary_data.prompt_data.window_mapping_reversed,
        session_start_time_str=session_start_time_str,
        session_duration=summary_data.prompt_data.prompt_data.metadata.duration,
    )
    str_inputs = [json.dumps(dataclasses.asdict(inputs))]
    # Start streaming the workflow
    handle = asyncio.run(_start_workflow(str_inputs=str_inputs, workflow_id=random_id))
    last_summary = ""
    while True:
        # Query the workflow for the current summary
        current_summary, desc = asyncio.run(_query_workflow_state(handle))
        # Yield only if there's new content
        if current_summary != last_summary:
            yield current_summary
            last_summary = current_summary
        # Check if workflow is complete
        if desc.status.name in ("COMPLETED", "FAILED", "CANCELED", "TERMINATED", "TIMED_OUT"):
            break
        # Small delay between queries to let new chunks come in
        time.sleep(0.1)


def stream_recording_summary(
    session_id: str,
    user_pk: int,
    team: Team,
    extra_summary_context: ExtraSummaryContext | None = None,
    local_reads_prod: bool = False,
) -> SyncIterableToAsync | Generator[str, None, None]:
    if SERVER_GATEWAY_INTERFACE == "ASGI":
        return _astream(
            session_id=session_id,
            user_pk=user_pk,
            team=team,
            extra_summary_context=extra_summary_context,
            local_reads_prod=local_reads_prod,
        )
    return excectute_test_summarize_session(
        session_id=session_id,
        user_pk=user_pk,
        team=team,
        extra_summary_context=extra_summary_context,
        local_reads_prod=local_reads_prod,
    )


def _astream(
    session_id: str,
    user_pk: int,
    team: Team,
    extra_summary_context: ExtraSummaryContext | None = None,
    local_reads_prod: bool = False,
) -> SyncIterableToAsync:
    return SyncIterableToAsync(
        excectute_test_summarize_session(
            session_id=session_id,
            user_pk=user_pk,
            team=team,
            extra_summary_context=extra_summary_context,
            local_reads_prod=local_reads_prod,
        )
    )
