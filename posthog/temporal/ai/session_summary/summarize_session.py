import asyncio
from collections.abc import Generator
from datetime import timedelta
import json
import time
import uuid
from redis import Redis
import structlog
import temporalio
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from django.conf import settings
from ee.session_recordings.session_summary.llm.consume import stream_llm_single_session_summary
from ee.session_recordings.session_summary.summarize_session import ExtraSummaryContext
from ee.session_recordings.session_summary.utils import serialize_to_sse_event
from posthog import constants
from posthog.redis import get_client
from posthog.models.team.team import Team
from posthog.temporal.ai.session_summary.shared import (
    SESSION_SUMMARIES_DB_DATA_REDIS_TTL,
    SingleSessionSummaryInputs,
    get_single_session_summary_llm_input_from_redis,
    fetch_session_data_activity,
)
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import async_connect
from temporalio.client import WorkflowHandle, WorkflowExecutionStatus
from temporalio.exceptions import ApplicationError

logger = structlog.get_logger(__name__)

# How often to poll for new chunks from the LLM stream
SESSION_SUMMARIES_STREAM_INTERVAL = 0.1  # 100ms


@temporalio.activity.defn
async def stream_llm_single_session_summary_activity(inputs: SingleSessionSummaryInputs) -> str:
    """Summarize a single session and stream the summary state as it becomes available"""
    if not inputs.redis_output_key:
        raise ApplicationError(
            f"Redis output key was not provided when summarizing session {inputs.session_id}: {inputs}",
            non_retryable=True,
        )
    # Creating client on each activity as we can't pass it in as an argument, and need it for both getting and storing data
    redis_client = get_client()
    llm_input = get_single_session_summary_llm_input_from_redis(
        redis_client=redis_client, redis_input_key=inputs.redis_input_key
    )
    last_summary_state = ""
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
        simplified_events_columns=llm_input.simplified_events_columns,
        url_mapping_reversed=llm_input.url_mapping_reversed,
        window_mapping_reversed=llm_input.window_mapping_reversed,
        # Session metadata
        session_start_time_str=llm_input.session_start_time_str,
        session_duration=llm_input.session_duration,
    )
    async for current_summary_state in session_summary_generator:
        if current_summary_state == last_summary_state:
            # Skip cases where no updates happened or the same state was sent again
            continue
        last_summary_state = current_summary_state
        # Store the last summary state in Redis
        # The size of the output is limited to <20kb, so compressing is excessive
        redis_client.setex(
            inputs.redis_output_key,
            SESSION_SUMMARIES_DB_DATA_REDIS_TTL,
            json.dumps({"last_summary_state": last_summary_state, "timestamp": time.time()}),
        )
        # Heartbeat to avoid workflow timeout, throttle to 5 seconds to avoid sending too many
        if time.time() - last_heartbeat_timestamp > 5:
            temporalio.activity.heartbeat()
            last_heartbeat_timestamp = time.time()
    return last_summary_state


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
            retry_policy=RetryPolicy(maximum_attempts=1),
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
    client = await async_connect()
    retry_policy = RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS))
    handle = await client.start_workflow(
        "summarize-session",
        inputs,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=constants.GENERAL_PURPOSE_TASK_QUEUE,
        retry_policy=retry_policy,
    )
    return handle


def _clean_up_redis(redis_client: Redis, redis_input_key: str, redis_output_key: str) -> None:
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
    shared_id = uuid.uuid4()
    # Prepare the input data
    redis_client = get_client()
    redis_input_key = f"session-summary:single:stream-input:{session_id}:{user_id}-{team.id}:{shared_id}"
    redis_output_key = f"session-summary:single:stream-output:{session_id}:{user_id}-{team.id}:{shared_id}"
    session_input = SingleSessionSummaryInputs(
        session_id=session_id,
        user_id=user_id,
        team_id=team.id,
        extra_summary_context=extra_summary_context,
        local_reads_prod=local_reads_prod,
        redis_input_key=redis_input_key,
        redis_output_key=redis_output_key,
    )
    # Connect to Temporal and start streaming the workflow
    workflow_id = f"session-summary:single:stream:{session_id}:{user_id}:{shared_id}"
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
                # No compression, as summaries are <20kb, so it's not worth it performance-wise
                redis_data_str = redis_data_raw.decode("utf-8") if isinstance(redis_data_raw, bytes) else redis_data_raw
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
