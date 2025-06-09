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
from ee.session_recordings.session_summary.utils import serialize_to_sse_event
from posthog.temporal.common.codec import EncryptionCodec
from temporalio.api.common.v1 import Payload
from posthog.models.team.team import Team
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import connect
from posthog.settings import SERVER_GATEWAY_INTERFACE
from temporalio.client import Client as TemporalClient, WorkflowHandle


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
    last_summary_state = ""
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
    async for current_summary_state in session_summary_generator:
        if current_summary_state == last_summary_state:
            # Skip cases where no updates happened or the same state was sent again
            continue
        last_summary_state = current_summary_state
        temporalio.activity.heartbeat({"last_summary_state": last_summary_state})
    return last_summary_state


@temporalio.workflow.defn(name="summarize-session")
class SummarizeSessionWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SessionSummaryInputs:
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


def execute_summarize_session(
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
        yield summary_data.sse_error_msg or serialize_to_sse_event(
            event_label="session-summary-error",
            event_data="Failed to prepare summary data",
        )
    # Checking here instead of in the preparation function to keep mypy happy
    if summary_data.prompt_data.prompt_data.metadata.start_time is None:
        raise ValueError(f"Session start time is missing in the session metadata for session_id {session_id}")
    if summary_data.prompt_data.prompt_data.metadata.duration is None:
        raise ValueError(f"Session duration is missing in the session metadata for session_id {session_id}")
    # Connect to the client and prepare the input
    random_id = str(uuid.uuid4())  # TODO: Generate a proper id
    session_start_time_str = summary_data.prompt_data.prompt_data.metadata.start_time.isoformat()
    # TODO: Store in Redis and send a key instead?
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
    last_summary_state = ""
    while True:
        desc = asyncio.run(handle.describe())
        # Access heartbeat details from activity
        if not desc.raw_description.pending_activities:
            continue
        for activity in desc.raw_description.pending_activities:
            if not activity.heartbeat_details:
                continue
            heartbeat_payloads = activity.heartbeat_details.payloads
            for payload in heartbeat_payloads:
                # Decode payloads
                decrypted_payload = Payload.FromString(EncryptionCodec(settings).decrypt(payload.data))
                # Get chunk
                data = decrypted_payload.data
                json_data = json.loads(data)
                current_summary_state = json_data.get("last_summary_state")
                if not current_summary_state or current_summary_state == last_summary_state:
                    # Skip cases where no updates happened or the same state was sent again
                    continue
                # Yield latest summary state
                last_summary_state = current_summary_state
                yield last_summary_state
            # Get the final result after workflow completes
        if desc.status.name == "COMPLETED":
            try:
                final_result = asyncio.run(handle.result())
                # Yield final result if it's different from the last state OR if we haven't yielded anything yet
                if final_result != last_summary_state or not last_summary_state:
                    yield final_result
            except Exception:
                # Handle any errors in getting the result
                pass
        # Check if workflow is completed unsuccessfully
        if desc.status.name in ("FAILED", "CANCELED", "TERMINATED", "TIMED_OUT"):
            # TODO: Handle errors
            break
        # Wait till next heartbeat to let new chunks come in from the stream
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
    return execute_summarize_session(
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
        execute_summarize_session(
            session_id=session_id,
            user_pk=user_pk,
            team=team,
            extra_summary_context=extra_summary_context,
            local_reads_prod=local_reads_prod,
        )
    )
