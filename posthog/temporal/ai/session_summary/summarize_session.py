import asyncio
from collections.abc import Generator
from dataclasses import dataclass
import dataclasses
from datetime import timedelta
import json
import time
import uuid
import aiohttp
import temporalio
from temporalio.api.common.v1 import Payload
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
from posthog.temporal.common.codec import EncryptionCodec


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
async def test_summary_activity(inputs: SessionSummaryInputs) -> SessionSummaryInputs:
    async with aiohttp.ClientSession() as session:
        async with session.get("http://httpbin.org/get") as resp:
            return await resp.text()


@temporalio.activity.defn
async def stream_llm_summary_activity(inputs: SessionSummaryInputs) -> str:
    last_chunk = ""
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
    # Iterate the async generator, store chunks, and return the combined result
    async for chunk in session_summary_generator:
        last_chunk = chunk
        # Send heartbeat with current accumulated content
        temporalio.activity.heartbeat({"last_chunk": last_chunk})
    return last_chunk


@temporalio.workflow.defn(name="summarize-session")
class SummarizeSessionWorkflow(PostHogWorkflow):
    def __init__(self):
        self.chunks: list[str] = []

    @temporalio.workflow.query
    def get_chunks(self) -> list[str]:
        """Query to get the current list of streamed chunks."""
        return self.chunks

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
    client = asyncio.run(
        connect(
            settings.TEMPORAL_HOST,
            settings.TEMPORAL_PORT,
            settings.TEMPORAL_NAMESPACE,
            server_root_ca_cert=settings.TEMPORAL_CLIENT_ROOT_CA,
            client_cert=settings.TEMPORAL_CLIENT_CERT,
            client_key=settings.TEMPORAL_CLIENT_KEY,
        )
    )
    retry_policy = RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS))
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
    handle = asyncio.run(
        client.start_workflow(
            "summarize-session",
            str_inputs,
            id=random_id,
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            task_queue=settings.TEMPORAL_TASK_QUEUE,
            retry_policy=retry_policy,
        )
    )
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
                last_chunk = json_data.get("last_chunk")
                if not last_chunk:
                    continue
                # Yield chunk
                yield last_chunk
        if desc.status.name in ("COMPLETED", "FAILED", "CANCELED", "TERMINATED", "TIMED_OUT"):
            break
        # Wait till next heartbeat
        time.sleep(0.5)


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
