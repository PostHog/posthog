import asyncio
from collections.abc import Generator
import dataclasses
from datetime import timedelta
import json
import time
from typing import cast
import uuid
from redis import Redis
import structlog
import temporalio
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from django.conf import settings
from ee.hogai.session_summaries import ExceptionToRetry
from ee.hogai.session_summaries.llm.consume import stream_llm_single_session_summary
from ee.hogai.session_summaries.session.summarize_session import (
    ExtraSummaryContext,
    SingleSessionSummaryLlmInputs,
    get_session_data_from_db,
    prepare_data_for_single_session_summary,
    prepare_single_session_summary_input,
)
from ee.hogai.session_summaries.utils import serialize_to_sse_event
from posthog import constants
from posthog.models.team.team import Team
from posthog.redis import get_client
from posthog.temporal.ai.session_summary.state import (
    StateActivitiesEnum,
    decompress_redis_data,
    generate_state_key,
    get_data_class_from_redis,
    get_redis_state_client,
    store_data_in_redis,
)
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import async_connect
from temporalio.client import WorkflowHandle, WorkflowExecutionStatus
from temporalio.exceptions import ApplicationError

logger = structlog.get_logger(__name__)

# How often to poll for new chunks from the LLM stream
SESSION_SUMMARIES_STREAM_INTERVAL = 0.1  # 100ms


@temporalio.activity.defn
async def fetch_session_data_activity(inputs: SingleSessionSummaryInputs) -> str | None:
    """Fetch data from DB for a single session and store/cache in Redis (to avoid hitting Temporal memory limits)"""
    redis_client, redis_input_key, _ = get_redis_state_client(
        key_base=inputs.redis_key_base,
        input_label=StateActivitiesEnum.SESSION_DB_DATA,
        state_id=inputs.session_id,
    )
    try:
        # Check if DB data is already in Redis. If it is and matched the target class - it's within TTL, so no need to re-fetch it from DB
        # TODO: Think about edge-cases like stale data for still-running sessions
        await get_data_class_from_redis(
            redis_client=redis_client,
            redis_key=redis_input_key,
            label=StateActivitiesEnum.SESSION_DB_DATA,
            target_class=SingleSessionSummaryLlmInputs,
        )
    except ValueError:
        # If not yet, or TTL expired - fetch data from DB
        session_db_data = await get_session_data_from_db(
            session_id=inputs.session_id,
            team_id=inputs.team_id,
            local_reads_prod=inputs.local_reads_prod,
        )
        summary_data = await prepare_data_for_single_session_summary(
            session_id=inputs.session_id,
            user_id=inputs.user_id,
            session_db_data=session_db_data,
            extra_summary_context=inputs.extra_summary_context,
        )
        if summary_data.error_msg is not None:
            # If we weren't able to collect the required data - retry
            logger.exception(
                f"Not able to fetch data from the DB for session {inputs.session_id} (by user {inputs.user_id}): {summary_data.error_msg}",
                session_id=inputs.session_id,
                user_id=inputs.user_id,
            )
            raise ExceptionToRetry()
        input_data = prepare_single_session_summary_input(
            session_id=inputs.session_id,
            user_id=inputs.user_id,
            summary_data=summary_data,
        )
        # Store the input in Redis
        input_data_str = json.dumps(dataclasses.asdict(input_data))
        await store_data_in_redis(
            redis_client=redis_client,
            redis_key=redis_input_key,
            data=input_data_str,
            label=StateActivitiesEnum.SESSION_DB_DATA,
        )
    # Nothing to return if the fetch was successful, as the data is stored in Redis
    return None


@temporalio.activity.defn
async def stream_llm_single_session_summary_activity(inputs: SingleSessionSummaryInputs) -> str:
    """Summarize a single session and stream the summary state as it becomes available"""
    if not inputs.redis_key_base:
        raise ApplicationError(
            f"Redis key base was not provided when summarizing session {inputs.session_id}: {inputs}",
            non_retryable=True,
        )
    # Creating client on each activity as we can't pass it in as an argument, and need it for both getting and storing data
    redis_client, redis_input_key, redis_output_key = get_redis_state_client(
        key_base=inputs.redis_key_base,
        input_label=StateActivitiesEnum.SESSION_DB_DATA,
        output_label=StateActivitiesEnum.SESSION_SUMMARY,
        state_id=inputs.session_id,
    )
    if not redis_input_key or not redis_output_key:
        raise ApplicationError(
            f"Redis input ({redis_input_key}) or output ({redis_output_key}) keys not provided when summarizing session {inputs.session_id}: {inputs}",
            non_retryable=True,
        )
    llm_input = cast(
        SingleSessionSummaryLlmInputs,
        await get_data_class_from_redis(
            redis_client=redis_client,
            redis_key=redis_input_key,
            label=StateActivitiesEnum.SESSION_DB_DATA,
            target_class=SingleSessionSummaryLlmInputs,
        ),
    )
    last_summary_state_str = ""
    temporalio.activity.heartbeat()
    last_heartbeat_timestamp = time.time()
    # Stream summary from the LLM stream
    session_summary_generator = stream_llm_single_session_summary(
        session_id=llm_input.session_id,
        user_id=llm_input.user_id,
        # Prompt
        summary_prompt=llm_input.summary_prompt,
        system_prompt=llm_input.system_prompt,
        # Mappings to enrich events
        allowed_event_ids=list(llm_input.simplified_events_mapping.keys()),
        simplified_events_mapping=llm_input.simplified_events_mapping,
        event_ids_mapping=llm_input.event_ids_mapping,
        simplified_events_columns=llm_input.simplified_events_columns,
        url_mapping_reversed=llm_input.url_mapping_reversed,
        window_mapping_reversed=llm_input.window_mapping_reversed,
        # Session metadata
        session_start_time_str=llm_input.session_start_time_str,
        session_duration=llm_input.session_duration,
        trace_id=temporalio.activity.info().workflow_id,
    )
    async for current_summary_state_str in session_summary_generator:
        if current_summary_state_str == last_summary_state_str:
            # Skip cases where no updates happened or the same state was sent again
            continue
        last_summary_state_str = current_summary_state_str
        # Store the last summary state in Redis
        await store_data_in_redis(
            redis_client=redis_client,
            redis_key=redis_output_key,
            data=json.dumps({"last_summary_state": last_summary_state_str, "timestamp": time.time()}),
            label=StateActivitiesEnum.SESSION_SUMMARY,
        )
        # Heartbeat to avoid workflow timeout, throttle to 5 seconds to avoid sending too many
        if time.time() - last_heartbeat_timestamp > 5:
            temporalio.activity.heartbeat()
            last_heartbeat_timestamp = time.time()
    return last_summary_state_str


@temporalio.workflow.defn(name="summarize-session")
class SummarizeSingleSessionWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SingleSessionSummaryInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return SingleSessionSummaryInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: SingleSessionSummaryInputs) -> str:
        await temporalio.workflow.execute_activity(
            fetch_session_data_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        summary = await temporalio.workflow.execute_activity(
            stream_llm_single_session_summary_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        return summary


async def _start_workflow(inputs: SingleSessionSummaryInputs, workflow_id: str) -> WorkflowHandle:
    """Start the single-session workflow and return its handle."""
    client = await async_connect()
    retry_policy = RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS))
    handle = await client.start_workflow(
        "summarize-session",
        inputs,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=constants.MAX_AI_TASK_QUEUE,
        retry_policy=retry_policy,
    )
    return handle


def _clean_up_redis(redis_client: Redis, redis_input_key: str, redis_output_key: str) -> None:
    """Remove temporary workflow data from Redis."""
    try:
        redis_client.delete(redis_input_key)
        redis_client.delete(redis_output_key)
    except Exception:
        # Log, but don't fail, as the records will be cleaned up by the TTL
        logger.exception(
            "Failed to clean up Redis keys for session summary",
            redis_input_key=redis_input_key,
            redis_output_key=redis_output_key,
        )


async def _check_handle_data(handle: WorkflowHandle) -> tuple[WorkflowExecutionStatus | None, str | None]:
    """Return workflow status and result if completed."""
    desc = await handle.describe()
    final_result = None
    if not desc.status:
        return None, None
    if desc.status == WorkflowExecutionStatus.COMPLETED:
        final_result = await handle.result()
    return desc.status, final_result


def execute_summarize_session_stream(
    session_id: str,
    user_id: int,
    team: Team,
    extra_summary_context: ExtraSummaryContext | None = None,
    local_reads_prod: bool = False,
) -> Generator[str, None, None]:
    """
    Start the workflow and yield summary state from the stream as it becomes available.
    """
    # Use shared identifier to be able to construct all the ids to check/debug
    # Using session id instead of random UUID to be able to check the data in Redis
    shared_id = session_id
    # Prepare the input data
    redis_key_base = f"session-summary:single:{user_id}-{team.id}:{shared_id}"
    # TODO: Write sync state client to use outside of asyncio
    redis_client = get_client()
    redis_input_key = generate_state_key(
        key_base=redis_key_base, label=StateActivitiesEnum.SESSION_DB_DATA, state_id=session_id
    )
    redis_output_key = generate_state_key(
        key_base=redis_key_base, label=StateActivitiesEnum.SESSION_SUMMARY, state_id=session_id
    )
    if not redis_input_key or not redis_output_key:
        raise ApplicationError(
            f"Redis input ({redis_input_key}) or output ({redis_output_key}) keys not provided when summarizing session {session_id}: {session_id}",
            non_retryable=True,
        )
    session_input = SingleSessionSummaryInputs(
        session_id=session_id,
        user_id=user_id,
        team_id=team.id,
        extra_summary_context=extra_summary_context,
        local_reads_prod=local_reads_prod,
        redis_key_base=redis_key_base,
    )
    # Connect to Temporal and start streaming the workflow
    workflow_id = f"session-summary:single:stream:{session_id}:{user_id}:{shared_id}:{uuid.uuid4()}"
    handle = asyncio.run(_start_workflow(inputs=session_input, workflow_id=workflow_id))
    last_summary_state = ""
    while True:
        try:
            # TODO: Rework to rely on Redis overly or reuse the loop to avoid creating new loops for each iteration
            status, final_result = asyncio.run(_check_handle_data(handle))
            # If no status yet, wait a bit
            if status is None:
                continue
            # If the workflow is completed
            if final_result is not None:
                # Yield final result if it's different from the last state OR if we haven't yielded anything yet
                if final_result != last_summary_state or not last_summary_state:
                    yield serialize_to_sse_event(
                        event_label="session-summary-stream",
                        event_data=final_result,
                    )
                _clean_up_redis(redis_client, redis_input_key, redis_output_key)
                return
            # Check if the workflow is completed unsuccessfully
            if status in (
                WorkflowExecutionStatus.FAILED,
                WorkflowExecutionStatus.CANCELED,
                WorkflowExecutionStatus.TERMINATED,
                WorkflowExecutionStatus.TIMED_OUT,
            ):
                yield serialize_to_sse_event(
                    event_label="session-summary-error",
                    event_data=f"Failed to generate summary: {status.name}",
                )
                _clean_up_redis(redis_client, redis_input_key, redis_output_key)
                return
            # If the workflow is still running
            redis_data_raw = redis_client.get(redis_output_key)
            if not redis_data_raw:
                continue  # No data stored yet
            try:
                redis_data_str = decompress_redis_data(redis_data_raw)
                redis_data = json.loads(redis_data_str)
            except Exception as e:
                raise ValueError(
                    f"Failed to parse Redis output data ({redis_data_raw}) for key {redis_output_key} when generating single session summary: {e}"
                )
            last_summary_state = redis_data.get("last_summary_state")
            if not last_summary_state:
                continue  # No data stored yet
            yield serialize_to_sse_event(
                event_label="session-summary-stream",
                event_data=last_summary_state,
            )
        except Exception:
            raise
        # Pause at finally to avoid querying instantly if no data stored yet or the state haven't changed
        finally:
            # Wait a bit to let new chunks come in from the stream
            time.sleep(SESSION_SUMMARIES_STREAM_INTERVAL)
