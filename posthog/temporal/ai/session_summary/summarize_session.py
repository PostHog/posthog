import json
import time
import uuid
import asyncio
import dataclasses
from collections.abc import Generator
from datetime import timedelta
from typing import Any, Literal, cast

from django.conf import settings

import structlog
import temporalio
import posthoganalytics
from dateutil import parser as dateutil_parser
from redis import Redis
from temporalio.client import WorkflowExecutionStatus, WorkflowHandle
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

from posthog.schema import ReplayInactivityPeriod

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.redis import get_client
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.activities import (
    CaptureTimingInputs,
    analyze_video_segment_activity,
    capture_timing_activity,
    consolidate_video_segments_activity,
    embed_and_store_segments_activity,
    prep_session_video_asset_activity,
    store_video_session_summary_activity,
    upload_video_to_gemini_activity,
)
from posthog.temporal.ai.session_summary.activities.video_validation import (
    validate_llm_single_session_summary_with_videos_activity,
)
from posthog.temporal.ai.session_summary.state import (
    StateActivitiesEnum,
    decompress_redis_data,
    generate_state_key,
    get_data_class_from_redis,
    get_redis_state_client,
    store_data_in_redis,
)
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs
from posthog.temporal.ai.session_summary.types.video import (
    VideoSegmentOutput,
    VideoSegmentSpec,
    VideoSummarySingleSessionInputs,
)
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import async_connect
from posthog.temporal.exports_video.workflow import VideoExportInputs

from ee.hogai.session_summaries import ExceptionToRetry
from ee.hogai.session_summaries.constants import (
    DEFAULT_VIDEO_UNDERSTANDING_MODEL,
    SESSION_SUMMARIES_STREAMING_MODEL,
    SESSION_SUMMARIES_SYNC_MODEL,
)
from ee.hogai.session_summaries.llm.consume import (
    get_exception_event_ids_from_summary,
    get_llm_single_session_summary,
    stream_llm_single_session_summary,
)
from ee.hogai.session_summaries.session.output_data import SessionSummarySerializer
from ee.hogai.session_summaries.session.summarize_session import (
    ExtraSummaryContext,
    SingleSessionSummaryLlmInputs,
    get_session_data_from_db,
    prepare_data_for_single_session_summary,
    prepare_single_session_summary_input,
)
from ee.hogai.session_summaries.utils import serialize_to_sse_event
from ee.models.session_summaries import SessionSummaryRunMeta, SingleSessionSummary

logger = structlog.get_logger(__name__)

# How often to poll for new chunks from the LLM stream
SESSION_SUMMARIES_STREAM_INTERVAL = 0.1  # 100ms
# How large the chunks should be when analyzing videos
SESSION_VIDEO_CHUNK_DURATION_S = 60
# How large should the active period be, so we still analyze it (or skip it, if it's smaller)
MIN_SESSION_PERIOD_DURATION_S = 1


@temporalio.activity.defn
async def fetch_session_data_activity(inputs: SingleSessionSummaryInputs) -> None:
    """Fetch data from DB for a single session and store/cache in Redis (to avoid hitting Temporal memory limits)"""
    # Check if the summary is already in the DB, so no need to fetch data from DB
    # Keeping thread-sensitive as checking for a single summary should be fast
    summary_exists = await database_sync_to_async(SingleSessionSummary.objects.summaries_exist)(
        team_id=inputs.team_id,
        session_ids=[inputs.session_id],
        extra_summary_context=inputs.extra_summary_context,
    )
    if summary_exists.get(inputs.session_id):
        # Skip data fetching as the ready summary will be returned in the next activity
        return None
    # If not - check if DB data is already in Redis. If it is and matched the target class - it's within TTL, so no need to re-fetch it from DB
    redis_client, redis_input_key, _ = get_redis_state_client(
        key_base=inputs.redis_key_base,
        input_label=StateActivitiesEnum.SESSION_DB_DATA,
        state_id=inputs.session_id,
    )
    success = await get_data_class_from_redis(
        redis_client=redis_client,
        redis_key=redis_input_key,
        label=StateActivitiesEnum.SESSION_DB_DATA,
        target_class=SingleSessionSummaryLlmInputs,
    )
    # Return if the data is properly cached
    if success is not None:
        return None
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
        temporalio.activity.logger.exception(
            f"Not able to fetch data from the DB for session {inputs.session_id} (by user {inputs.user_id}): {summary_data.error_msg}",
            extra={
                "session_id": inputs.session_id,
                "user_id": inputs.user_id,
                "signals_type": "session-summaries",
            },
        )
        raise ExceptionToRetry(summary_data.error_msg)
    input_data = prepare_single_session_summary_input(
        session_id=inputs.session_id,
        user_id=inputs.user_id,
        user_distinct_id_to_log=inputs.user_distinct_id_to_log,
        summary_data=summary_data,
        model_to_use=inputs.model_to_use,
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


def _store_final_summary_in_db_from_activity(
    inputs: SingleSessionSummaryInputs,
    session_summary: SessionSummarySerializer,
    llm_input: SingleSessionSummaryLlmInputs,
) -> None:
    """Store the final summary in the DB from the activity"""
    exception_event_ids = get_exception_event_ids_from_summary(session_summary)
    # Getting the user explicitly from the DB as we can't pass models between activities
    user = User.objects.get(id=inputs.user_id)
    if not user:
        msg = f"User with id {inputs.user_id} not found, when trying to add session summary for session {inputs.session_id}"
        temporalio.activity.logger.error(
            msg,
            extra={
                "user_id": inputs.user_id,
                "session_id": inputs.session_id,
                "signals_type": "session-summaries",
            },
        )
        raise ValueError(msg)
    # Disable thread-sensitive as the summary could be pretty heavy and it's a write
    SingleSessionSummary.objects.add_summary(
        session_id=inputs.session_id,
        team_id=inputs.team_id,
        summary=session_summary,
        exception_event_ids=exception_event_ids,
        extra_summary_context=inputs.extra_summary_context,
        run_metadata=SessionSummaryRunMeta(
            model_used=inputs.model_to_use,
            visual_confirmation=False,
        ),
        session_start_time=dateutil_parser.isoparse(llm_input.session_start_time_str),
        session_duration=llm_input.session_duration,
        distinct_id=llm_input.distinct_id,
        created_by=user,
    )


@temporalio.activity.defn
async def get_llm_single_session_summary_activity(
    inputs: SingleSessionSummaryInputs,
) -> None:
    """Summarize a single session in one call and store/cache in Redis (to avoid hitting Temporal memory limits)"""
    # Check if summary is already in the DB (in case of race conditions/multiple group summaries running in parallel/etc.)
    # Keeping thread-sensitive as checking for a single summary should be fast
    summary_exists = await database_sync_to_async(SingleSessionSummary.objects.summaries_exist)(
        team_id=inputs.team_id,
        session_ids=[inputs.session_id],
        extra_summary_context=inputs.extra_summary_context,
    )
    if summary_exists.get(inputs.session_id):
        # Stored successfully, no need to summarize again
        return None
    # Base key includes session ids, so when summarizing this session again, but with different inputs (or order) - we don't use cache
    redis_client, redis_input_key, _ = get_redis_state_client(
        key_base=inputs.redis_key_base,
        input_label=StateActivitiesEnum.SESSION_DB_DATA,
        state_id=inputs.session_id,
    )
    # If not yet - generate the summary with LLM
    llm_input_raw = await get_data_class_from_redis(
        redis_client=redis_client,
        redis_key=redis_input_key,
        label=StateActivitiesEnum.SESSION_DB_DATA,
        target_class=SingleSessionSummaryLlmInputs,
    )
    if llm_input_raw is None:
        # No reason to retry activity, as the input data is not in Redis
        msg = f"No LLM input found for session {inputs.session_id} when summarizing"
        temporalio.activity.logger.error(
            msg,
            extra={
                "session_id": inputs.session_id,
                "signals_type": "session-summaries",
            },
        )
        raise ApplicationError(msg, non_retryable=True)
    llm_input = cast(
        SingleSessionSummaryLlmInputs,
        llm_input_raw,
    )
    # Get summary from LLM
    session_summary = await get_llm_single_session_summary(
        session_id=llm_input.session_id,
        user_id=llm_input.user_id,
        model_to_use=llm_input.model_to_use,
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
        user_distinct_id=llm_input.user_distinct_id_to_log,
    )
    # Store the final summary in the DB
    await database_sync_to_async(_store_final_summary_in_db_from_activity, thread_sensitive=False)(
        inputs, session_summary, llm_input
    )
    # Returning nothing as output is stored in Redis + Postgres
    return None


@temporalio.activity.defn
async def stream_llm_single_session_summary_activity(
    inputs: SingleSessionSummaryInputs,
) -> str:
    """Summarize a single session and stream the summary state as it becomes available"""
    # Check if summary is already in the DB, so no need to summarize again
    # Disabling thread-sensitive as summaries can be heavy to load from DB
    ready_summary = await database_sync_to_async(SingleSessionSummary.objects.get_summary, thread_sensitive=False)(
        team_id=inputs.team_id,
        session_id=inputs.session_id,
        extra_summary_context=inputs.extra_summary_context,
    )
    if ready_summary is not None:
        # Return the ready summary straight away
        return json.dumps(ready_summary.summary)
    # If not - summarize and stream through Redis
    if not inputs.redis_key_base:
        msg = f"Redis key base was not provided when summarizing session {inputs.session_id}: {inputs}"
        temporalio.activity.logger.error(
            msg,
            extra={
                "session_id": inputs.session_id,
                "signals_type": "session-summaries",
            },
        )
        raise ApplicationError(msg, non_retryable=True)
    # Creating client on each activity as we can't pass it in as an argument, and need it for both getting and storing data
    redis_client, redis_input_key, redis_output_key = get_redis_state_client(
        key_base=inputs.redis_key_base,
        input_label=StateActivitiesEnum.SESSION_DB_DATA,
        output_label=StateActivitiesEnum.SESSION_SUMMARY,
        state_id=inputs.session_id,
    )
    if not redis_input_key or not redis_output_key:
        msg = f"Redis input ({redis_input_key}) or output ({redis_output_key}) keys not provided when summarizing session {inputs.session_id}: {inputs}"
        temporalio.activity.logger.error(
            msg,
            extra={
                "session_id": inputs.session_id,
                "signals_type": "session-summaries",
            },
        )
        raise ApplicationError(msg, non_retryable=True)
    llm_input_raw = await get_data_class_from_redis(
        redis_client=redis_client,
        redis_key=redis_input_key,
        label=StateActivitiesEnum.SESSION_DB_DATA,
        target_class=SingleSessionSummaryLlmInputs,
    )
    if llm_input_raw is None:
        # No reason to retry activity, as the input data is not in Redis
        msg = f"No LLM input found for session {inputs.session_id} when summarizing (stream)"
        temporalio.activity.logger.error(
            msg,
            extra={
                "session_id": inputs.session_id,
                "signals_type": "session-summaries",
            },
        )
        raise ApplicationError(msg, non_retryable=True)
    llm_input = cast(SingleSessionSummaryLlmInputs, llm_input_raw)
    last_summary_state_str = ""
    temporalio.activity.heartbeat()
    last_heartbeat_timestamp = time.time()
    # Stream summary from the LLM stream
    session_summary_generator = stream_llm_single_session_summary(
        session_id=llm_input.session_id,
        user_id=llm_input.user_id,
        model_to_use=llm_input.model_to_use,
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
        user_distinct_id=llm_input.user_distinct_id_to_log,
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
    # As the stream is finished, store the final summary in the DB
    session_summary = SessionSummarySerializer(data=json.loads(last_summary_state_str))
    session_summary.is_valid(raise_exception=True)
    await database_sync_to_async(_store_final_summary_in_db_from_activity, thread_sensitive=False)(
        inputs, session_summary, llm_input
    )
    # Return the last state as string to finish the function execution
    return last_summary_state_str


@temporalio.workflow.defn(name="summarize-session-stream")
class SummarizeSingleSessionStreamWorkflow(PostHogWorkflow):
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


@temporalio.workflow.defn(name="summarize-session")
class SummarizeSingleSessionWorkflow(PostHogWorkflow):
    @staticmethod
    def parse_inputs(inputs: list[str]) -> SingleSessionSummaryInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return SingleSessionSummaryInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: SingleSessionSummaryInputs) -> None:
        start_time = temporalio.workflow.now()
        await temporalio.workflow.execute_activity(
            fetch_session_data_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        await ensure_llm_single_session_summary(inputs)
        duration_seconds = (temporalio.workflow.now() - start_time).total_seconds()
        await temporalio.workflow.execute_activity(
            capture_timing_activity,
            CaptureTimingInputs(
                distinct_id=inputs.user_distinct_id_to_log,
                team_id=inputs.team_id,
                session_id=inputs.session_id,
                timing_type="single_session_flow",
                duration_seconds=duration_seconds,
                success=True,
                extra_properties={
                    "video_validation_enabled": inputs.video_validation_enabled,
                },
            ),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


def _validate_period(
    period: ReplayInactivityPeriod, video_duration: float, index: int, inactivity_periods_count: int
) -> tuple[float, float, float, float] | None:
    # Filter to only active periods (skip gaps and idle time)
    if not period.active:
        return None
    # If the period wasn't able to get the start recording timestamp - it's either too short or buggy to process, skipping
    if period.recording_ts_from_s is None:
        return None
    # If the period has no ts_to_s - it's probably the last period, so set it to the video duration
    if period.ts_to_s is None:
        # Raise exception if it's not the last period
        if index != inactivity_periods_count - 1:
            msg = f"Inactivity period has no ts_to_s, while not being the last period ({index}/{inactivity_periods_count - 1}): {period.model_dump_json()}"
            logger.error(msg, signals_type="session-summaries")
            raise ValueError(msg)
        period.recording_ts_to_s = video_duration
        # Calculate the ts_to_s accordingly
        period.ts_to_s = period.ts_from_s + (period.recording_ts_to_s - period.recording_ts_from_s)
    # If the recording end period is still empty - there's a problem in calculations
    if period.recording_ts_to_s is None:
        msg = f"Inactivity period has no recording_ts_to_s: {period.model_dump_json()}"
        logger.error(msg, signals_type="session-summaries")
        raise ValueError(msg)
    # Validate the period data
    session_period_start = period.ts_from_s
    session_period_end = period.ts_to_s
    recording_period_start = period.recording_ts_from_s
    recording_period_end = period.recording_ts_to_s
    # Skip periods that are too short, as they won't bring any value to the summary
    # Checking for >= 0 to still fail on negative durations
    recording_period_duration = recording_period_end - recording_period_start
    if recording_period_duration >= 0 and recording_period_duration < MIN_SESSION_PERIOD_DURATION_S:
        logger.warning(
            f"Skipping period {index} of {inactivity_periods_count - 1} because it's too short: {recording_period_end - recording_period_start}s < {MIN_SESSION_PERIOD_DURATION_S}s",
            signals_type="session-summaries",
        )
        return None
    # Incorrect time ranges
    if round(recording_period_end, 2) <= round(recording_period_start, 2):
        msg = f"Invalid recording period time range: recording_ts_from_s={recording_period_start}, recording_ts_to_s={recording_period_end}"
        logger.error(msg, signals_type="session-summaries")
        raise ValueError(msg)
    if round(session_period_end, 2) <= round(session_period_start, 2):
        msg = f"Invalid session period time range: ts_from_s={session_period_start}, ts_to_s={session_period_end}"
        logger.error(msg, signals_type="session-summaries")
        raise ValueError(msg)
    if round(recording_period_end, 2) > round(video_duration, 2):
        # Could happen, log for visibility, but don't raise
        logger.warning(
            "Recording timestamp exceeds video duration: "
            f"recording_ts_to_s={recording_period_end}, video_duration={video_duration}",
            signals_type="session-summaries",
        )
    if round(recording_period_end - recording_period_start, 2) != round(session_period_end - session_period_start, 2):
        # Could happen, log for visibility, but don't raise
        logger.warning(
            "Recording/session periods duration mismatch: "
            f"recording_duration={recording_period_end - recording_period_start}, "
            f"session_duration={session_period_end - session_period_start}",
            signals_type="session-summaries",
        )
    return session_period_start, session_period_end, recording_period_start, recording_period_end


def calculate_video_segment_specs(
    video_duration: float,
    chunk_duration: float,
    inputs: SingleSessionSummaryInputs,
    inactivity_periods: list[ReplayInactivityPeriod] | None = None,
) -> list[VideoSegmentSpec]:
    # Assume that inactivity data should be successfully collected for any session, so no need to split into random chunks
    if not inactivity_periods:
        msg = f"Inactivity periods were not provided to calculate video segment specs"
        logger.error(
            msg,
            session_id=inputs.session_id,
            team_id=inputs.team_id,
            user_id=inputs.user_id,
            signals_type="session-summaries",
        )
        err = ValueError(msg)
        capture_exception(
            err,
            additional_properties={
                "session_id": inputs.session_id,
                "team_id": inputs.team_id,
                "user_id": inputs.user_id,
            },
        )
        raise err
    # If inactivity data is present - only analyze "active" periods (when user was interacting)
    segments: list[VideoSegmentSpec] = []
    segment_index = 0
    # TODO: Add more logic to avoid splitting right after jumping to the new page
    for i, period in enumerate(inactivity_periods):
        validation = _validate_period(period, video_duration, i, len(inactivity_periods))
        if validation is None:
            # Skip the periods that are too short or failed validation
            continue
        session_period_start, session_period_end, recording_period_start, recording_period_end = validation
        # Start either after the rendering delay, or at the previous chunk end
        if recording_period_end - recording_period_start <= chunk_duration:
            # If the period smaller than the expected chunk duration - process as is
            segments.append(
                VideoSegmentSpec(
                    segment_index=segment_index,
                    start_time=session_period_start,
                    end_time=session_period_end,
                    recording_start_time=recording_period_start,
                    recording_end_time=recording_period_end,
                )
            )
            segment_index += 1
            continue
        # If the period is larger than chunk_duration, split it into chunks small enough for efficient LLM processing
        current_recording_period_start = recording_period_start
        # Iterate while not reaching the end of the period
        while current_recording_period_start < recording_period_end:
            current_recording_period_end = current_recording_period_start + chunk_duration
            remaining_after_chunk = recording_period_end - current_recording_period_end
            # If the remaining portion after this chunk would be smaller than a new chunk, extend the current chunk
            if remaining_after_chunk > 0 and remaining_after_chunk < chunk_duration:
                current_recording_period_end = recording_period_end
            # Continue creating new chunks if there are plenty of activity left in the period
            else:
                current_recording_period_end = min(current_recording_period_end, recording_period_end)
            # Calculate session timestamps based on the recording timestamps
            current_session_period_start = session_period_start + (
                current_recording_period_start - recording_period_start
            )
            current_session_period_end = session_period_start + (current_recording_period_end - recording_period_start)
            # Define a new segment to process
            segments.append(
                VideoSegmentSpec(
                    segment_index=segment_index,
                    start_time=current_session_period_start,
                    end_time=current_session_period_end,
                    recording_start_time=current_recording_period_start,
                    recording_end_time=current_recording_period_end,
                )
            )
            segment_index += 1
            current_recording_period_start = current_recording_period_end
    return segments


async def ensure_llm_single_session_summary(inputs: SingleSessionSummaryInputs):
    retry_policy = RetryPolicy(maximum_attempts=3)
    trace_id = temporalio.workflow.info().workflow_id

    if inputs.video_validation_enabled != "full":
        # Run "classic" event-based summarization
        await temporalio.workflow.execute_activity(
            get_llm_single_session_summary_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry_policy,
        )
        if inputs.video_validation_enabled:
            await temporalio.workflow.execute_activity(
                validate_llm_single_session_summary_with_videos_activity,
                inputs,
                start_to_close_timeout=timedelta(minutes=10),
                retry_policy=retry_policy,
            )
        return

    # Full video-based summarization:
    # Convert inputs to video workflow format
    video_inputs = VideoSummarySingleSessionInputs(
        session_id=inputs.session_id,
        user_id=inputs.user_id,
        user_distinct_id_to_log=inputs.user_distinct_id_to_log,
        team_id=inputs.team_id,
        redis_key_base=inputs.redis_key_base,
        model_to_use=DEFAULT_VIDEO_UNDERSTANDING_MODEL,
        extra_summary_context=inputs.extra_summary_context,
    )

    # Activity 1: Prepare video export (find or create ExportedAsset)
    export_result = await temporalio.workflow.execute_activity(
        prep_session_video_asset_activity,
        video_inputs,
        start_to_close_timeout=timedelta(minutes=3),
        retry_policy=retry_policy,
    )

    # Skip video-based summarization if session is too short
    if export_result is None:
        return

    asset_id = export_result.asset_id

    # If the asset needs rendering, run the video export as a child workflow
    if export_result.needs_export:
        workflow_id = f"session-video-summary-export_{video_inputs.team_id}_{video_inputs.session_id}"
        await temporalio.workflow.execute_child_workflow(
            "export-video",
            VideoExportInputs(exported_asset_id=asset_id, use_puppeteer=True),
            id=workflow_id,
            task_queue=settings.VIDEO_EXPORT_TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS)),
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            execution_timeout=timedelta(hours=3),
        )

    # Activity 2: Upload full video to Gemini (single upload)
    upload_result = await temporalio.workflow.execute_activity(
        upload_video_to_gemini_activity,
        args=(video_inputs, asset_id),
        start_to_close_timeout=timedelta(minutes=10),
        retry_policy=retry_policy,
    )
    uploaded_video = upload_result["uploaded_video"]
    team_name = upload_result["team_name"]
    inactivity_periods = upload_result["inactivity_periods"]

    # Calculate segment specs based on video duration and activity periods
    segment_specs = calculate_video_segment_specs(
        video_duration=uploaded_video.duration,
        chunk_duration=SESSION_VIDEO_CHUNK_DURATION_S,
        inputs=inputs,
        inactivity_periods=inactivity_periods,
    )

    # Activity 3: Analyze all segments in parallel (max 100 concurrent to limit blast radius)
    semaphore = asyncio.Semaphore(100)

    async def _analyze_segment_with_semaphore(segment_spec: VideoSegmentSpec):
        async with semaphore:
            return await temporalio.workflow.execute_activity(
                analyze_video_segment_activity,
                args=(video_inputs, uploaded_video, segment_spec, trace_id, team_name),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

    segment_tasks = [_analyze_segment_with_semaphore(segment_spec) for segment_spec in segment_specs]
    segment_results = await asyncio.gather(*segment_tasks, return_exceptions=True)

    # Flatten results from all segments
    raw_segments: list[VideoSegmentOutput] = []
    for result in segment_results:
        if isinstance(result, Exception):
            posthoganalytics.capture_exception(
                result,
                distinct_id=inputs.user_distinct_id_to_log,
                properties={"$session_id": inputs.session_id},
            )
            logger.exception(
                f"Error analyzing video segment for session {inputs.session_id}: {result}",
                signals_type="session-summaries",
            )
            continue
        raw_segments.extend(cast(list[VideoSegmentOutput], result))

    # Activity 4: Consolidate raw segments into meaningful semantic segments
    consolidated_analysis = await temporalio.workflow.execute_activity(
        consolidate_video_segments_activity,
        args=(video_inputs, raw_segments, trace_id),
        start_to_close_timeout=timedelta(minutes=3),
        retry_policy=retry_policy,
    )

    # Activity 5: Generate embeddings for all segments and store in ClickHouse via Kafka
    await temporalio.workflow.execute_activity(
        embed_and_store_segments_activity,
        args=(video_inputs, consolidated_analysis.segments),
        start_to_close_timeout=timedelta(minutes=5),
        retry_policy=retry_policy,
    )

    # Activity 6: Store video-based summary in database
    # This activity retrieves the cached event data from Redis (from fetch_session_data_activity)
    # and uses it to map video segments to real events
    await temporalio.workflow.execute_activity(
        store_video_session_summary_activity,
        args=(video_inputs, consolidated_analysis),
        start_to_close_timeout=timedelta(minutes=5),
        retry_policy=retry_policy,
    )


async def _execute_single_session_summary_workflow(inputs: SingleSessionSummaryInputs, workflow_id: str) -> None:
    """Execute the single-session summary workflow without streaming."""
    client = await async_connect()
    retry_policy = RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS))
    await client.execute_workflow(
        "summarize-session",
        inputs,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=settings.MAX_AI_TASK_QUEUE,
        retry_policy=retry_policy,
    )


async def _start_single_session_summary_workflow_stream(
    inputs: SingleSessionSummaryInputs, workflow_id: str
) -> WorkflowHandle:
    """Start the single-session stream workflow and return its handle."""
    client = await async_connect()
    retry_policy = RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS))
    handle = await client.start_workflow(
        "summarize-session-stream",
        inputs,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=settings.MAX_AI_TASK_QUEUE,
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
            signals_type="session-summaries",
        )


async def _check_handle_data(
    handle: WorkflowHandle,
) -> tuple[WorkflowExecutionStatus | None, str | None]:
    """Return workflow status and result if completed."""
    desc = await handle.describe()
    final_result = None
    if not desc.status:
        return None, None
    if desc.status == WorkflowExecutionStatus.COMPLETED:
        final_result = await handle.result()
    return desc.status, final_result


def _prepare_execution(
    session_id: str,
    user: User,
    team: Team,
    model_to_use: str,
    stream: bool = False,
    extra_summary_context: ExtraSummaryContext | None = None,
    local_reads_prod: bool = False,
    video_validation_enabled: bool | Literal["full"] | None = None,
) -> tuple[Redis, str, str, SingleSessionSummaryInputs, str]:
    # Use shared identifier to be able to construct all the ids to check/debug
    # Using session id instead of random UUID to be able to check the data in Redis
    shared_id = session_id
    # Prepare the input data
    redis_key_base = f"session-summary:single:{user.id}-{team.id}:{shared_id}"
    redis_client = get_client()
    redis_input_key = generate_state_key(
        key_base=redis_key_base,
        label=StateActivitiesEnum.SESSION_DB_DATA,
        state_id=session_id,
    )
    redis_output_key = generate_state_key(
        key_base=redis_key_base,
        label=StateActivitiesEnum.SESSION_SUMMARY,
        state_id=session_id,
    )
    if not redis_input_key or not redis_output_key:
        msg = f"Redis input ({redis_input_key}) or output ({redis_output_key}) keys not provided when summarizing session {session_id}: {session_id}"
        logger.error(msg, session_id=session_id, signals_type="session-summaries")
        raise ApplicationError(msg, non_retryable=True)
    session_input = SingleSessionSummaryInputs(
        session_id=session_id,
        user_id=user.id,
        user_distinct_id_to_log=user.distinct_id,
        team_id=team.id,
        extra_summary_context=extra_summary_context,
        local_reads_prod=local_reads_prod,
        redis_key_base=redis_key_base,
        model_to_use=model_to_use,
        video_validation_enabled=video_validation_enabled,
    )
    workflow_id = (
        f"session-summary:single:{'stream' if stream else 'direct'}:{team.id}:{session_id}:{shared_id}:{uuid.uuid4()}"
    )
    return redis_client, redis_input_key, redis_output_key, session_input, workflow_id


async def execute_summarize_session(
    session_id: str,
    user: User,
    team: Team,
    model_to_use: str | None = None,
    extra_summary_context: ExtraSummaryContext | None = None,
    local_reads_prod: bool = False,
    video_validation_enabled: bool | Literal["full"] | None = None,
) -> dict[str, Any]:
    """
    Start the direct summarization workflow (no streaming) and return the summary.
    Intended to use as a part of other tools or workflows to get more context on summary, so implemented async.
    """
    if model_to_use is None:
        model_to_use = (
            SESSION_SUMMARIES_SYNC_MODEL if video_validation_enabled != "full" else DEFAULT_VIDEO_UNDERSTANDING_MODEL
        )
    _, _, _, session_input, workflow_id = _prepare_execution(
        session_id=session_id,
        user=user,
        team=team,
        stream=False,
        model_to_use=model_to_use,
        extra_summary_context=extra_summary_context,
        local_reads_prod=local_reads_prod,
        video_validation_enabled=video_validation_enabled,
    )
    # Wait for the workflow to complete
    try:
        await _execute_single_session_summary_workflow(inputs=session_input, workflow_id=workflow_id)
    except WorkflowAlreadyStartedError:
        # Workflow is already running, wait for it to complete
        client = await async_connect()
        handle = client.get_workflow_handle(workflow_id)
        await handle.result()
    # Get the summary from the DB
    summary_row = await database_sync_to_async(SingleSessionSummary.objects.get_summary, thread_sensitive=False)(
        team_id=team.id,
        session_id=session_id,
        extra_summary_context=extra_summary_context,
    )
    if not summary_row:
        msg = f"No ready summary found in DB when generating single session summary for session {session_id}"
        logger.error(msg, session_id=session_id, signals_type="session-summaries")
        raise ValueError(msg)
    summary = summary_row.summary
    return summary


def execute_summarize_session_stream(
    session_id: str,
    user: User,
    team: Team,
    model_to_use: str = SESSION_SUMMARIES_STREAMING_MODEL,
    extra_summary_context: ExtraSummaryContext | None = None,
    local_reads_prod: bool = False,
    video_validation_enabled: bool | None = None,
) -> Generator[str, None, None]:
    """
    Start the streaming workflow and yield summary state from the stream as it becomes available.
    Intended to use straight-to-frontend direct communication, so implemented as a generator.
    """
    redis_client, redis_input_key, redis_output_key, session_input, workflow_id = _prepare_execution(
        session_id=session_id,
        user=user,
        team=team,
        stream=True,
        model_to_use=model_to_use,
        extra_summary_context=extra_summary_context,
        local_reads_prod=local_reads_prod,
        video_validation_enabled=video_validation_enabled,
    )
    # Connect to Temporal and start the workflow
    handle = asyncio.run(_start_single_session_summary_workflow_stream(inputs=session_input, workflow_id=workflow_id))
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
                msg = f"Failed to parse Redis output data ({redis_data_raw}) for key {redis_output_key} when generating single session summary: {e}"
                logger.exception(
                    msg,
                    redis_output_key=redis_output_key,
                    signals_type="session-summaries",
                )
                raise ValueError(msg)
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
