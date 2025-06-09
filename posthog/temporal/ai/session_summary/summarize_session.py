import asyncio
from collections.abc import Generator
from dataclasses import dataclass
import dataclasses
from datetime import timedelta
import json
import time
import uuid
from redis import Redis
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
from posthog.redis import get_client
from posthog.temporal.common.codec import EncryptionCodec
from temporalio.api.common.v1 import Payload
from posthog.models.team.team import Team
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


def _get_input_data_from_redis(redis_client: Redis, redis_input_key: str) -> tuple[str, SessionSummaryInputs]:
    raw_redis_data = redis_client.get(redis_input_key)
    if not raw_redis_data:
        raise ValueError(
            f"Input data not found in Redis for key {redis_input_key} when generating single session summary"
        )
    if not isinstance(raw_redis_data, str):
        raise ValueError(
            f"Input data is not a string in Redis for key {redis_input_key} when generating single session summary, but {type(raw_redis_data)}: {raw_redis_data}"
        )
    try:
        redis_data = json.loads(raw_redis_data)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse input data ({raw_redis_data}): {e}")
    redis_output_key = redis_data.get("output_key")
    if not redis_output_key:
        raise ValueError(
            f"Output key not found in Redis for key {redis_input_key} when generating single session summary: {redis_data}"
        )
    input_data = redis_data.get("input_data")
    if not input_data:
        raise ValueError(
            f"Input data not found in Redis for key {redis_input_key} when generating single session summary: {redis_data}"
        )
    try:
        summary_inputs = SessionSummaryInputs(**input_data)
    except Exception as e:
        raise ValueError(f"Session summary input data is not valid ({input_data}): {e}")
    return redis_output_key, summary_inputs


@temporalio.activity.defn
async def stream_llm_summary_activity(redis_input_key: str) -> str:
    # Creating client on each activity as we can't pass it in as an argument, and need it for both getting and storing data
    redis_client = get_client()
    redis_output_key, summary_inputs = _get_input_data_from_redis(
        redis_client=redis_client, redis_input_key=redis_input_key
    )
    last_summary_state = ""
    session_summary_generator = stream_llm_session_summary(
        session_id=summary_inputs.session_id,
        user_pk=summary_inputs.user_pk,
        summary_prompt=summary_inputs.summary_prompt,
        system_prompt=summary_inputs.system_prompt,
        allowed_event_ids=list(summary_inputs.simplified_events_mapping.keys()),
        simplified_events_mapping=summary_inputs.simplified_events_mapping,
        simplified_events_columns=summary_inputs.simplified_events_columns,
        url_mapping_reversed=summary_inputs.url_mapping_reversed,
        window_mapping_reversed=summary_inputs.window_mapping_reversed,
        session_start_time_str=summary_inputs.session_start_time_str,
        session_duration=summary_inputs.session_duration,
    )
    async for current_summary_state in session_summary_generator:
        if current_summary_state == last_summary_state:
            # Skip cases where no updates happened or the same state was sent again
            continue
        last_summary_state = current_summary_state
        # Store the last summary state in Redis
        redis_client.setex(
            redis_output_key,
            900,  # 15 minutes TTL to keep alive for retries
            json.dumps({"last_summary_state": last_summary_state, "timestamp": time.time()}),
        )
        # Heartbeat to avoid workflow timeout
        temporalio.activity.heartbeat()
    return last_summary_state


@temporalio.workflow.defn(name="summarize-session")
class SummarizeSessionWorkflow:
    @temporalio.workflow.run
    async def run(self, redis_input_key: str) -> str:
        result = await temporalio.workflow.execute_activity(
            stream_llm_summary_activity,
            redis_input_key,
            start_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return result


async def _start_workflow(redis_input_key: str, workflow_id: str) -> WorkflowHandle:
    client = await _connect_to_temporal_client()
    retry_policy = RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS))
    handle = await client.start_workflow(
        "summarize-session",
        redis_input_key,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=settings.TEMPORAL_TASK_QUEUE,
        retry_policy=retry_policy,
    )
    return handle


def _decode_payload(payload_data: bytes) -> str | None:
    try:
        decrypted_payload = Payload.FromString(EncryptionCodec(settings).decrypt(payload_data))
        data = decrypted_payload.data
        json_data = json.loads(data)
        last_summary_state = json_data.get("last_summary_state")
        if not isinstance(last_summary_state, str):
            return None
        return last_summary_state
    except Exception:
        return None


def _clean_up_redis(redis_client: Redis, redis_input_key: str, redis_output_key: str) -> None:
    redis_client.delete(redis_input_key)
    redis_client.delete(redis_output_key)


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
        return
    # Checking here instead of in the preparation function to keep mypy happy
    if summary_data.prompt_data.prompt_data.metadata.start_time is None:
        raise ValueError(f"Session start time is missing in the session metadata for session_id {session_id}")
    if summary_data.prompt_data.prompt_data.metadata.duration is None:
        raise ValueError(f"Session duration is missing in the session metadata for session_id {session_id}")

    # Prepare the input
    input_data = SessionSummaryInputs(
        session_id=session_id,
        user_pk=user_pk,
        summary_prompt=summary_data.prompt.summary_prompt,
        system_prompt=summary_data.prompt.system_prompt,
        simplified_events_mapping=summary_data.prompt_data.simplified_events_mapping,
        simplified_events_columns=summary_data.prompt_data.prompt_data.columns,
        url_mapping_reversed=summary_data.prompt_data.url_mapping_reversed,
        window_mapping_reversed=summary_data.prompt_data.window_mapping_reversed,
        session_start_time_str=summary_data.prompt_data.prompt_data.metadata.start_time.isoformat(),
        session_duration=summary_data.prompt_data.prompt_data.metadata.duration,
    )
    # Connect to Redis and prepare the input
    redis_client = get_client()
    redis_input_key = f"session_summary:single:stream-input:{session_id}:{user_pk}:{uuid.uuid4()}"
    redis_output_key = f"session_summary:single:stream-output:{session_id}:{user_pk}:{uuid.uuid4()}"
    redis_client.setex(
        redis_input_key,
        900,  # 15 minutes TTL to keep alive for retries
        json.dumps(
            {
                "input_data": dataclasses.asdict(input_data),
                "output_key": redis_output_key,
            }
        ),
    )
    # Connect to Temporal and start streaming the workflow
    workflow_id = f"session-summary:single:{session_id}:{user_pk}:{uuid.uuid4()}"
    handle = asyncio.run(_start_workflow(redis_input_key=redis_input_key, workflow_id=workflow_id))
    last_summary_state = ""
    while True:
        desc = asyncio.run(handle.describe())
        if desc.status.name == "COMPLETED":
            try:
                final_result = asyncio.run(handle.result())
                # Yield final result if it's different from the last state OR if we haven't yielded anything yet
                if final_result != last_summary_state or not last_summary_state:
                    yield final_result
                _clean_up_redis(redis_client, redis_input_key, redis_output_key)
                return
            except Exception:
                # TODO: Handle any errors in getting the result
                pass
        # Check if workflow is completed unsuccessfully
        if desc.status.name in ("FAILED", "CANCELED", "TERMINATED", "TIMED_OUT"):
            # Handle failure - yield an error message
            yield serialize_to_sse_event(
                event_label="session-summary-error",
                event_data=f"Failed to generate summary: {desc.status.name}",
            )
            _clean_up_redis(redis_client, redis_input_key, redis_output_key)
            return
        # If the workflow is still running, get current summary state from Redis
        redis_data_raw = redis_client.get(redis_output_key)
        if not redis_data_raw:
            continue
        try:
            redis_data = json.loads(redis_data_raw)
        except json.JSONDecodeError:
            raise ValueError(
                f"Failed to parse Redis output data ({redis_data_raw}) for key {redis_output_key} when generating single session summary"
            )
        last_summary_state = redis_data.get("last_summary_state")
        if not isinstance(last_summary_state, str):
            continue
        yield last_summary_state
        # Wait a bit to let new chunks come in from the stream
        time.sleep(0.05)


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
