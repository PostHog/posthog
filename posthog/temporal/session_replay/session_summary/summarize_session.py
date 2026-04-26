import json
import asyncio
import dataclasses
from collections.abc import AsyncGenerator
from datetime import timedelta
from typing import Any, cast

from django.conf import settings

import structlog
import temporalio
import posthoganalytics
from dateutil import parser as dateutil_parser
from redis import Redis
from temporalio.client import WorkflowExecutionStatus, WorkflowHandle
from temporalio.common import RetryPolicy, SearchAttributePair, TypedSearchAttributes, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError, WorkflowAlreadyStartedError

from posthog.schema import ReplayInactivityPeriod

from posthog.exceptions_capture import capture_exception
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.redis import get_client
from posthog.sync import database_sync_to_async
from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.common.client import async_connect
from posthog.temporal.common.search_attributes import POSTHOG_TEAM_ID_KEY
from posthog.temporal.session_replay.rasterize_recording.types import RasterizeRecordingInputs
from posthog.temporal.session_replay.session_summary.activities import (
    CaptureTimingInputs,
    analyze_video_segment_activity,
    capture_timing_activity,
    cleanup_gemini_file_activity,
    consolidate_video_segments_activity,
    embed_and_store_segments_activity,
    emit_session_problem_signals_activity,
    prep_session_video_asset_activity,
    store_video_session_summary_activity,
    tag_and_highlight_session_activity,
    upload_video_to_gemini_activity,
)
from posthog.temporal.session_replay.session_summary.state import (
    StateActivitiesEnum,
    generate_state_key,
    get_data_class_from_redis,
    get_redis_state_client,
    store_data_in_redis,
)
from posthog.temporal.session_replay.session_summary.types.single import (
    SingleSessionProgress,
    SingleSessionSummaryInputs,
)
from posthog.temporal.session_replay.session_summary.types.video import (
    VideoSegmentOutput,
    VideoSegmentSpec,
    VideoSummarySingleSessionInputs,
    collect_session_problems,
)

from ee.hogai.session_summaries.constants import DEFAULT_VIDEO_UNDERSTANDING_MODEL, SESSION_SUMMARIES_MODEL
from ee.hogai.session_summaries.llm.consume import get_exception_event_ids_from_summary, get_llm_single_session_summary
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

# How large the chunks should be when analyzing videos
SESSION_VIDEO_CHUNK_DURATION_S = 60
# How large should the active period be, so we still analyze it (or skip it, if it's smaller)
MIN_SESSION_PERIOD_DURATION_S = 1

# Phase order for the video-based single-session flow. Drives the step
# counter in the get_progress workflow query so the frontend can render
# "Step N of M" along with a named phase label.
VIDEO_PHASE_ORDER: tuple[str, ...] = (
    "fetching_data",
    "preparing_video",
    "rendering_video",
    "uploading_to_gemini",
    "analyzing_segments",
    "consolidating",
    "generating_embeddings",
    "saving_summary",
    "cleanup",
)
VIDEO_PHASE_INDEX: dict[str, int] = {name: idx for idx, name in enumerate(VIDEO_PHASE_ORDER)}
VIDEO_TOTAL_STEPS: int = len(VIDEO_PHASE_ORDER)


def _set_phase(progress: SingleSessionProgress | None, phase: str) -> None:
    """Update the workflow's progress dict in place if present.

    A no-op for the event-based flow and the group flow, which pass ``None``.
    """
    if progress is None:
        return
    progress["phase"] = phase
    if phase in VIDEO_PHASE_INDEX:
        progress["step"] = VIDEO_PHASE_INDEX[phase]


@temporalio.activity.defn
async def fetch_session_data_activity(inputs: SingleSessionSummaryInputs) -> bool:
    """Fetch data from DB for a single session and store/cache in Redis (to avoid hitting Temporal memory limits).
    Returns True if the data was fetched successfully, False if the session has no associated events (probably static).
    """
    # Check if the summary is already in the DB, so no need to fetch data from DB
    # Keeping thread-sensitive as checking for a single summary should be fast
    summary_exists = await database_sync_to_async(SingleSessionSummary.objects.summaries_exist)(
        team_id=inputs.team_id,
        session_ids=[inputs.session_id],
        extra_summary_context=inputs.extra_summary_context,
    )
    if summary_exists.get(inputs.session_id):
        # Skip data fetching as the ready summary will be returned in the next activity
        return True
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
        return True
    # If not yet, or TTL expired - fetch data from DB
    session_db_data = await get_session_data_from_db(
        session_id=inputs.session_id,
        team_id=inputs.team_id,
        local_reads_prod=inputs.local_reads_prod,
    )
    if not session_db_data.session_events or not session_db_data.session_events_columns:
        return False  # Recording has no associated events, so it's probably static - let's skip this the session
    summary_data = await prepare_data_for_single_session_summary(
        session_id=inputs.session_id,
        user_id=inputs.user_id,
        session_db_data=session_db_data,
        extra_summary_context=inputs.extra_summary_context,
    )
    input_data = prepare_single_session_summary_input(
        session_id=inputs.session_id,
        user_id=inputs.user_id,
        user_distinct_id_to_log=inputs.user_distinct_id_to_log,
        summary_data=summary_data,
        model_to_use=inputs.model_to_use,
        trigger_session_id=inputs.trigger_session_id,
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
    return True


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
        trigger_session_id=llm_input.trigger_session_id,
    )
    # Store the final summary in the DB
    await database_sync_to_async(_store_final_summary_in_db_from_activity, thread_sensitive=False)(
        inputs, session_summary, llm_input
    )
    # Returning nothing as output is stored in Redis + Postgres
    return None


@temporalio.workflow.defn(name="summarize-session")
class SummarizeSingleSessionWorkflow(PostHogWorkflow):
    @classmethod
    def workflow_id_for(cls, team_id: int, session_id: str) -> str:
        """Stable Temporal workflow id (per team and session)."""
        return f"session-summary:single:{team_id}:{session_id}"

    def __init__(self) -> None:
        self._progress: SingleSessionProgress = {
            "phase": "starting",
            "step": 0,
            "total_steps": VIDEO_TOTAL_STEPS,
            "rasterizer_workflow_id": None,
            "segments_total": 0,
            "segments_completed": 0,
        }

    @temporalio.workflow.query
    def get_progress(self) -> SingleSessionProgress:
        """Snapshot of the current summarization progress.

        Read by the backend polling loop that proxies phase transitions back
        to the browser over SSE. Only the video flow populates meaningful
        values — the event-based flow keeps the defaults.
        """
        # Copy so Temporal can serialize the snapshot without races.
        return cast(SingleSessionProgress, dict(self._progress))

    @staticmethod
    def parse_inputs(inputs: list[str]) -> SingleSessionSummaryInputs:
        """Parse inputs from the management command CLI."""
        loaded = json.loads(inputs[0])
        return SingleSessionSummaryInputs(**loaded)

    @temporalio.workflow.run
    async def run(self, inputs: SingleSessionSummaryInputs) -> None:
        start_time = temporalio.workflow.now()
        # Only the video flow reports progress via workflow queries.
        progress = self._progress if inputs.video_based else None
        _set_phase(progress, "fetching_data")
        session_got_data = await temporalio.workflow.execute_activity(
            fetch_session_data_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=3),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        if not session_got_data:
            return None  # If the session got no data, skip it
        await ensure_llm_single_session_summary(inputs, progress=progress)
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
                    "video_based": inputs.video_based,
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


async def ensure_llm_single_session_summary(
    inputs: SingleSessionSummaryInputs,
    progress: SingleSessionProgress | None = None,
):
    """Run the single-session summary flow.

    If ``progress`` is provided (only by ``SummarizeSingleSessionWorkflow``
    for the video flow), phase transitions and segment counts are written
    into it so the workflow's ``get_progress`` query can expose them.
    """
    retry_policy = RetryPolicy(maximum_attempts=3)
    trace_id = temporalio.workflow.info().workflow_id

    if not inputs.video_based:
        # Run event-based summarization
        await temporalio.workflow.execute_activity(
            get_llm_single_session_summary_activity,
            inputs,
            start_to_close_timeout=timedelta(minutes=5),
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
    _set_phase(progress, "preparing_video")
    export_result = await temporalio.workflow.execute_activity(
        prep_session_video_asset_activity,
        video_inputs,
        start_to_close_timeout=timedelta(minutes=3),
        retry_policy=retry_policy,
    )

    # Skip video-based summarization if session is too short or summary already exists
    if export_result is None:
        return

    asset_id = export_result.asset_id

    # If the asset needs rendering, run the rasterizer as a child workflow
    if export_result.needs_export:
        _set_phase(progress, "rendering_video")
        workflow_id = f"session-video-summary-rasterize_{video_inputs.team_id}_{video_inputs.session_id}"
        if progress is not None:
            progress["rasterizer_workflow_id"] = workflow_id
        await temporalio.workflow.execute_child_workflow(
            "rasterize-recording",
            RasterizeRecordingInputs(exported_asset_id=asset_id),
            id=workflow_id,
            task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
            retry_policy=RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS)),
            id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
            execution_timeout=timedelta(minutes=30),
        )

    # Activity 2: Upload full video to Gemini (single upload)
    _set_phase(progress, "uploading_to_gemini")
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

    # Activity 8 (cleanup) must run even if activities 3-7 fail
    try:
        # Activity 3: Analyze all segments in parallel (max 100 concurrent to limit blast radius)
        _set_phase(progress, "analyzing_segments")
        if progress is not None:
            progress["segments_total"] = len(segment_specs)
            progress["segments_completed"] = 0
        semaphore = asyncio.Semaphore(100)

        async def _analyze_segment_with_semaphore(segment_spec: VideoSegmentSpec):
            async with semaphore:
                result = await temporalio.workflow.execute_activity(
                    analyze_video_segment_activity,
                    args=(video_inputs, uploaded_video, segment_spec, trace_id, team_name),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=retry_policy,
                )
                if progress is not None:
                    progress["segments_completed"] += 1
                return result

        segment_tasks = [_analyze_segment_with_semaphore(segment_spec) for segment_spec in segment_specs]
        segment_results = await asyncio.gather(*segment_tasks, return_exceptions=True)

        # Flatten results from all segments
        raw_segments: list[VideoSegmentOutput] = []
        for result in segment_results:
            if isinstance(result, Exception):
                posthoganalytics.capture_exception(
                    result,
                    distinct_id=inputs.user_distinct_id_to_log,
                )
                logger.exception(
                    f"Error analyzing video segment for session {inputs.session_id}: {result}",
                    signals_type="session-summaries",
                )
                continue
            raw_segments.extend(cast(list[VideoSegmentOutput], result))

        # Activity 4: Consolidate raw segments into meaningful semantic segments,
        # then tag the session in a follow-up turn of the same conversation
        _set_phase(progress, "consolidating")
        consolidation_output = await temporalio.workflow.execute_activity(
            consolidate_video_segments_activity,
            args=(video_inputs, raw_segments, trace_id),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=retry_policy,
        )

        consolidated_analysis = consolidation_output["consolidated_analysis"]
        tagging = consolidation_output["tagging"]

        # Activity 5: Enqueue embedding requests for each segment via Kafka.
        # The activity just produces Kafka messages and returns; actual embedding
        # computation happens asynchronously in the embedding worker.
        _set_phase(progress, "generating_embeddings")
        await temporalio.workflow.execute_activity(
            embed_and_store_segments_activity,
            args=(video_inputs, consolidated_analysis.segments),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=retry_policy,
        )

        # Activities 6a + 6b run in parallel when some segment would emit a problem signal;
        # otherwise skip 6a entirely.
        _set_phase(progress, "saving_summary")
        problems = collect_session_problems(consolidated_analysis.segments)
        logger.info(
            "session problem signals pre-emission",
            team_id=inputs.team_id,
            session_id=inputs.session_id,
            workflow_id=trace_id,
            total_consolidated_segments=len(consolidated_analysis.segments),
            problem_segment_count=len(problems),
            problems=[p.model_dump(include={"problem_type", "start_time", "end_time"}) for p in problems[:30]],
            will_run_emit_activity=bool(problems),
            signals_type="session-summaries",
        )
        if problems:
            emit_result, store_result = await asyncio.gather(
                temporalio.workflow.execute_activity(
                    emit_session_problem_signals_activity,
                    args=(video_inputs, problems),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=retry_policy,
                ),
                temporalio.workflow.execute_activity(
                    store_video_session_summary_activity,
                    args=(video_inputs, consolidated_analysis, export_result.team_api_token),
                    start_to_close_timeout=timedelta(minutes=5),
                    retry_policy=retry_policy,
                ),
                return_exceptions=True,
            )
            if isinstance(emit_result, Exception):
                posthoganalytics.capture_exception(
                    emit_result,
                    distinct_id=inputs.user_distinct_id_to_log,
                )
                logger.exception(
                    f"Error emitting session problem signals for session {inputs.session_id}: {emit_result}",
                    signals_type="session-summaries",
                )
            if isinstance(store_result, BaseException):
                raise store_result
        else:
            logger.info(
                "Skipping session problem signals emission activity (no problems found)",
                team_id=inputs.team_id,
                session_id=inputs.session_id,
                workflow_id=trace_id,
                total_consolidated_segments=len(consolidated_analysis.segments),
                signals_type="session-summaries",
            )
            await temporalio.workflow.execute_activity(
                store_video_session_summary_activity,
                args=(video_inputs, consolidated_analysis, export_result.team_api_token),
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=retry_policy,
            )

        # Activity 7: Write tags and highlight flag to ClickHouse via Kafka
        _set_phase(progress, "tagging")
        await temporalio.workflow.execute_activity(
            tag_and_highlight_session_activity,
            args=(video_inputs, tagging),
            start_to_close_timeout=timedelta(minutes=2),
            retry_policy=retry_policy,
        )
    finally:
        # Activity 8: Delete uploaded video from Gemini to free storage quota
        _set_phase(progress, "cleanup")
        await temporalio.workflow.execute_activity(
            cleanup_gemini_file_activity,
            args=(uploaded_video.gemini_file_name, inputs.session_id),
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )


async def _start_video_summary_workflow(inputs: SingleSessionSummaryInputs, workflow_id: str) -> WorkflowHandle:
    """Start the video-based single-session summary workflow and return its handle.

    Non-blocking alternative to ``_execute_single_session_summary_workflow`` so
    the API layer can poll the ``get_progress`` query while the workflow runs.
    """
    client = await async_connect()
    retry_policy = RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS))
    handle = await client.start_workflow(
        "summarize-session",
        inputs,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
        retry_policy=retry_policy,
        search_attributes=TypedSearchAttributes(
            search_attributes=[SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=inputs.team_id)]
        ),
    )
    return handle


async def _execute_single_session_summary_workflow(inputs: SingleSessionSummaryInputs, workflow_id: str) -> None:
    """Execute the single-session summary workflow."""
    client = await async_connect()
    retry_policy = RetryPolicy(maximum_attempts=int(settings.TEMPORAL_WORKFLOW_MAX_ATTEMPTS))
    await client.execute_workflow(
        "summarize-session",
        inputs,
        id=workflow_id,
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
        task_queue=settings.SESSION_REPLAY_TASK_QUEUE,
        retry_policy=retry_policy,
        search_attributes=TypedSearchAttributes(
            search_attributes=[SearchAttributePair(key=POSTHOG_TEAM_ID_KEY, value=inputs.team_id)]
        ),
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
    extra_summary_context: ExtraSummaryContext | None = None,
    local_reads_prod: bool = False,
    video_based: bool = False,
    trigger_session_id: str | None = None,
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
        video_based=video_based,
        trigger_session_id=trigger_session_id,
    )
    workflow_id = SummarizeSingleSessionWorkflow.workflow_id_for(team.id, session_id)
    return redis_client, redis_input_key, redis_output_key, session_input, workflow_id


async def execute_summarize_session(
    session_id: str,
    user: User,
    team: Team,
    model_to_use: str | None = None,
    extra_summary_context: ExtraSummaryContext | None = None,
    local_reads_prod: bool = False,
    video_based: bool = False,
    trigger_session_id: str | None = None,
) -> dict[str, Any]:
    """
    Start the summarization workflow and return the summary.
    Intended to use as a part of other tools or workflows to get more context on summary, so implemented async.
    """
    # Check if summary already exists before starting the Temporal workflow
    existing_summary = await database_sync_to_async(SingleSessionSummary.objects.get_summary, thread_sensitive=False)(
        team_id=team.id,
        session_id=session_id,
        extra_summary_context=extra_summary_context,
    )
    if existing_summary is not None:
        return existing_summary.summary
    if model_to_use is None:
        model_to_use = SESSION_SUMMARIES_MODEL if not video_based else DEFAULT_VIDEO_UNDERSTANDING_MODEL
    _, _, _, session_input, workflow_id = _prepare_execution(
        session_id=session_id,
        user=user,
        team=team,
        model_to_use=model_to_use,
        extra_summary_context=extra_summary_context,
        local_reads_prod=local_reads_prod,
        video_based=video_based,
        trigger_session_id=trigger_session_id,
    )
    # Wait for the workflow to complete
    try:
        await _execute_single_session_summary_workflow(inputs=session_input, workflow_id=workflow_id)
    except WorkflowAlreadyStartedError:
        # Workflow is already running, wait for it to complete
        client = await async_connect()
        handle = client.get_workflow_handle(workflow_id)
        await handle.result()
    # Get the ready summary from the DB
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


# How often the video-flow polling loop queries workflow progress.
VIDEO_PROGRESS_POLL_INTERVAL_S = 2.0


async def _get_rasterizer_frame_progress(client: Any, rasterizer_workflow_id: str) -> dict[str, Any] | None:
    """Query the rasterizer child workflow for its phase and read frame-level
    progress from the currently-running activity's heartbeat details.

    Returns a dict with ``phase`` and optional ``frame_progress`` (``frame``,
    ``estimatedTotalFrames``), or ``None`` if the child workflow isn't
    queryable yet or the query fails. Errors are swallowed intentionally —
    progress reporting must never break the summary flow.
    """
    try:
        child_handle = client.get_workflow_handle(rasterizer_workflow_id)
        phase_info: dict[str, Any] = await child_handle.query("get_progress")

        frame_progress: dict[str, Any] | None = None
        desc = await child_handle.describe()
        # raw_description carries the gRPC payload with encrypted heartbeat details
        pending = getattr(desc.raw_description, "pending_activities", None) or []
        if pending:
            raw_payloads = list(pending[0].heartbeat_details.payloads)
            if raw_payloads:
                codec = getattr(client.data_converter, "payload_codec", None)
                decoded = await codec.decode(raw_payloads) if codec is not None else raw_payloads
                if decoded:
                    frame_progress = json.loads(decoded[0].data)

        return {**phase_info, "frame_progress": frame_progress}
    except Exception as e:
        logger.debug(
            "Failed to read rasterizer progress (non-fatal)",
            rasterizer_workflow_id=rasterizer_workflow_id,
            error=str(e),
            signals_type="session-summaries",
        )
        return None


async def execute_summarize_session_video_stream(
    session_id: str,
    user: User,
    team: Team,
    extra_summary_context: ExtraSummaryContext | None = None,
    local_reads_prod: bool = False,
) -> AsyncGenerator[str, None]:
    """Start the video-based summarization workflow and stream progress events.

    Yields SSE-formatted ``session-summary-progress`` events every few seconds
    while the workflow runs, and a final ``session-summary-stream`` event with
    the completed summary payload (or ``session-summary-error`` on failure).

    The entire polling loop runs inside a single event loop so the Temporal
    client and workflow handle — both of which hold asyncio-bound state — are
    reused safely across iterations.
    """
    # Fast path: if a summary already exists, yield it immediately and skip Temporal entirely.
    existing_summary = await database_sync_to_async(SingleSessionSummary.objects.get_summary, thread_sensitive=False)(
        team_id=team.id, session_id=session_id, extra_summary_context=extra_summary_context
    )
    if existing_summary is not None:
        logger.info(
            "video summary fast path: returning cached summary",
            session_id=session_id,
            signals_type="session-summaries",
        )
        yield serialize_to_sse_event(
            event_label="session-summary-stream",
            event_data=json.dumps(existing_summary.summary),
        )
        return

    _, _, _, session_input, workflow_id = _prepare_execution(
        session_id=session_id,
        user=user,
        team=team,
        model_to_use=DEFAULT_VIDEO_UNDERSTANDING_MODEL,
        extra_summary_context=extra_summary_context,
        local_reads_prod=local_reads_prod,
        video_based=True,
    )

    client = await async_connect()
    try:
        handle = await _start_video_summary_workflow(inputs=session_input, workflow_id=workflow_id)
    except WorkflowAlreadyStartedError:
        handle = client.get_workflow_handle(workflow_id)

    logger.info(
        "video summary polling loop starting",
        workflow_id=workflow_id,
        session_id=session_id,
        signals_type="session-summaries",
    )

    while True:
        try:
            status, _final_result = await _check_handle_data(handle)
            if status is None:
                await asyncio.sleep(VIDEO_PROGRESS_POLL_INTERVAL_S)
                continue

            if status == WorkflowExecutionStatus.COMPLETED:
                # The workflow writes the summary to Postgres rather than
                # returning it, so load it from the DB the same way
                # execute_summarize_session does.
                summary_row = await database_sync_to_async(
                    SingleSessionSummary.objects.get_summary, thread_sensitive=False
                )(team_id=team.id, session_id=session_id, extra_summary_context=extra_summary_context)
                if not summary_row:
                    yield serialize_to_sse_event(
                        event_label="session-summary-error",
                        event_data="Something went wrong while generating the summary. Please try again.",
                    )
                    return
                yield serialize_to_sse_event(
                    event_label="session-summary-stream",
                    event_data=json.dumps(summary_row.summary),
                )
                return

            if status in (
                WorkflowExecutionStatus.FAILED,
                WorkflowExecutionStatus.CANCELED,
                WorkflowExecutionStatus.TERMINATED,
                WorkflowExecutionStatus.TIMED_OUT,
            ):
                status_messages = {
                    WorkflowExecutionStatus.FAILED: "Something went wrong while generating the summary. Please try again.",
                    WorkflowExecutionStatus.CANCELED: "The summary generation was canceled.",
                    WorkflowExecutionStatus.TERMINATED: "The summary generation was terminated unexpectedly. Please try again.",
                    WorkflowExecutionStatus.TIMED_OUT: "The summary generation timed out. The recording may be too long or complex. Please try again.",
                }
                yield serialize_to_sse_event(
                    event_label="session-summary-error",
                    event_data=status_messages[status],
                )
                return

            # Workflow is still running — query for structured progress.
            progress_payload: dict[str, Any]
            try:
                progress_payload = await handle.query("get_progress")
            except Exception as e:
                logger.info(
                    "get_progress query failed (workflow may not be ready yet)",
                    workflow_id=workflow_id,
                    error=str(e),
                    error_type=type(e).__name__,
                    signals_type="session-summaries",
                )
                await asyncio.sleep(VIDEO_PROGRESS_POLL_INTERVAL_S)
                continue

            rasterizer_workflow_id = progress_payload.get("rasterizer_workflow_id")
            if progress_payload.get("phase") == "rendering_video" and rasterizer_workflow_id:
                progress_payload["rasterizer"] = await _get_rasterizer_frame_progress(client, rasterizer_workflow_id)
            else:
                progress_payload["rasterizer"] = None

            logger.info(
                "yielding session-summary-progress event",
                workflow_id=workflow_id,
                phase=progress_payload.get("phase"),
                step=progress_payload.get("step"),
                signals_type="session-summaries",
            )
            yield serialize_to_sse_event(
                event_label="session-summary-progress",
                event_data=json.dumps(progress_payload),
            )

            await asyncio.sleep(VIDEO_PROGRESS_POLL_INTERVAL_S)
        except Exception as e:
            capture_exception(e)
            yield serialize_to_sse_event(
                event_label="session-summary-error",
                event_data="Something went wrong while generating the summary. Please try again.",
            )
            return
