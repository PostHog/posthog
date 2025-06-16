import asyncio
from collections.abc import Generator
from dataclasses import dataclass
import dataclasses
from datetime import timedelta
import gzip
import json
import time
import uuid
from redis import Redis
import structlog
import temporalio
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from django.conf import settings
from ee.session_recordings.session_summary.llm.consume import stream_llm_session_summary
from ee.session_recordings.session_summary.summarize_session import (
    ExtraSummaryContext,
    SingleSessionSummaryLlmInputs,
    prepare_data_for_single_session_summary,
    prepare_single_session_summary_input,
)
from temporalio.exceptions import ApplicationError
from ee.session_recordings.session_summary.utils import serialize_to_sse_event
from posthog import constants
from posthog.redis import get_client
from posthog.models.team.team import Team
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import async_connect
from temporalio.client import WorkflowHandle, WorkflowExecutionStatus

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, kw_only=True)
class SingleSessionSummaryInputs:
    """Workflow input to get summary for a single session"""

    session_id: str
    user_pk: int
    team_id: int
    redis_input_key: str
    redis_output_key: str
    extra_summary_context: ExtraSummaryContext | None = None
    local_reads_prod: bool = False


def _get_single_session_summary_llm_input_from_redis(
    redis_client: Redis, redis_input_key: str
) -> SingleSessionSummaryLlmInputs:
    raw_redis_data = redis_client.get(redis_input_key)
    if not raw_redis_data:
        raise ValueError(f"Single session summary LLM input data not found in Redis for key {redis_input_key}")
    try:
        # Decompress the data
        if isinstance(raw_redis_data, bytes):
            redis_data_str = gzip.decompress(raw_redis_data).decode("utf-8")
        else:
            # Fallback for uncompressed data (if stored as string)
            redis_data_str = raw_redis_data
        redis_data = SingleSessionSummaryLlmInputs(**json.loads(redis_data_str))
    except Exception as e:
        raise ValueError(
            f"Failed to parse single session summary LLM input data ({raw_redis_data}) for Redis key {redis_input_key}: {e}"
        )
    return redis_data


def _compress_llm_input_data(llm_input_data: SingleSessionSummaryLlmInputs) -> bytes:
    return gzip.compress(json.dumps(dataclasses.asdict(llm_input_data)).encode("utf-8"))


@temporalio.activity.defn
async def fetch_session_data_activity(session_input: SingleSessionSummaryInputs) -> str | None:
    """Fetch data from DB and store in Redis (to avoid hitting Temporal memory limits), return Redis key"""
    summary_data = await prepare_data_for_single_session_summary(
        session_id=session_input.session_id,
        user_pk=session_input.user_pk,
        team_id=session_input.team_id,
        extra_summary_context=session_input.extra_summary_context,
        local_reads_prod=session_input.local_reads_prod,
    )
    if summary_data.sse_error_msg is not None:
        # If we weren't able to collect the required data - retry
        raise ApplicationError(summary_data.sse_error_msg, non_retryable=False)
    input_data = prepare_single_session_summary_input(
        session_id=session_input.session_id,
        user_pk=session_input.user_pk,
        summary_data=summary_data,
    )
    # Connect to Redis and prepare the input
    redis_client = get_client()
    compressed_llm_input_data = _compress_llm_input_data(input_data)
    redis_client.setex(
        session_input.redis_input_key,
        900,  # 15 minutes TTL to keep alive for retries
        compressed_llm_input_data,
    )
    # Nothing to return if the fetch was successful, as the data is stored in Redis
    return None


@temporalio.activity.defn
async def stream_llm_single_session_summary_activity(session_input: SingleSessionSummaryInputs) -> str:
    # Creating client on each activity as we can't pass it in as an argument, and need it for both getting and storing data
    redis_client = get_client()
    llm_input = _get_single_session_summary_llm_input_from_redis(
        redis_client=redis_client, redis_input_key=session_input.redis_input_key
    )
    last_summary_state = ""
    temporalio.activity.heartbeat()
    last_heartbeat_timestamp = time.time()
    # Stream SSE-formated summary data from LLM
    session_summary_generator = stream_llm_session_summary(
        session_id=llm_input.session_id,
        user_pk=llm_input.user_pk,
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
            session_input.redis_output_key,
            900,  # 15 minutes TTL to keep alive for retries
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
    async def run(self, session_input: SingleSessionSummaryInputs) -> str:
        await temporalio.workflow.execute_activity(
            fetch_session_data_activity,
            session_input,
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=RetryPolicy(maximum_attempts=1),
        )
        sse_summary = await temporalio.workflow.execute_activity(
            stream_llm_single_session_summary_activity,
            session_input,
            start_to_close_timeout=timedelta(minutes=5),
            heartbeat_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        temporalio.workflow.logger.info(
            f"Successfully executed summarize-session workflow with id {temporalio.workflow.info().workflow_id}"
        )
        return sse_summary


async def _start_workflow(session_input: SingleSessionSummaryInputs, workflow_id: str) -> WorkflowHandle:
    client = await async_connect()
    retry_policy = RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS))
    handle = await client.start_workflow(
        "summarize-session",
        session_input,
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


def execute_summarize_session(
    session_id: str,
    user_pk: int,
    team: Team,
    extra_summary_context: ExtraSummaryContext | None = None,
    local_reads_prod: bool = False,
) -> Generator[str, None, None]:
    """
    Start the workflow and yield summary state from the stream as it becomes available.
    """
    # Prepare the input data
    redis_client = get_client()
    redis_input_key = f"session_summary:single:stream-input:{session_id}:{user_pk}:{uuid.uuid4()}"
    redis_output_key = f"session_summary:single:stream-output:{session_id}:{user_pk}:{uuid.uuid4()}"
    session_input = SingleSessionSummaryInputs(
        session_id=session_id,
        user_pk=user_pk,
        team_id=team.id,
        extra_summary_context=extra_summary_context,
        local_reads_prod=local_reads_prod,
        redis_input_key=redis_input_key,
        redis_output_key=redis_output_key,
    )
    # Connect to Temporal and start streaming the workflow
    workflow_id = f"session-summary:single:{session_id}:{user_pk}:{uuid.uuid4()}"
    handle = asyncio.run(_start_workflow(session_input=session_input, workflow_id=workflow_id))
    last_summary_state = ""
    while True:
        try:
            status, final_result = asyncio.run(_check_handle_data(handle))
            # If no status yet, wait a bit
            if status is None:
                continue
            # If the workflow is completed
            if final_result is not None:
                # Yield final result if it's different from the last state OR if we haven't yielded anything yet
                if final_result != last_summary_state or not last_summary_state:
                    yield final_result
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
            yield last_summary_state
        except Exception:
            raise
        # Pause at finally to avoid querying instantly if no data stored yet or the state haven't changed
        finally:
            # Wait a bit (50ms) to let new chunks come in from the stream
            time.sleep(0.05)
