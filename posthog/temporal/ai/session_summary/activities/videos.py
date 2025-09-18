from math import ceil
from typing import cast

import temporalio
from temporalio.exceptions import ApplicationError

from posthog.models.user import User
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs

from ee.hogai.session_summaries.constants import (
    FAILED_MOMENTS_MIN_RATIO,
    SECONDS_BEFORE_EVENT_FOR_VALIDATION_VIDEO,
    VALIDATION_VIDEO_DURATION,
)
from ee.hogai.session_summaries.session.output_data import EnrichedKeyActionSerializer, SessionSummarySerializer
from ee.hogai.videos.session_moments import SessionMomentInput, SessionMomentsLLMAnalyzer
from ee.models.session_summaries import SingleSessionSummary


def _prepare_moment_input_from_summary_event(
    event: EnrichedKeyActionSerializer, session_id: str
) -> SessionMomentInput | None:
    event_uuid = event.data["event_uuid"]
    ms_from_start = event.data.get("milliseconds_since_start")
    if ms_from_start is None:
        temporalio.workflow.logger.error(
            f"Milliseconds since start not found in the event {event_uuid} for session {session_id} when generating video for validating session summary",
        )
        return None
    event_timestamp = ceil(ms_from_start / 1000)
    # Start a video a couple of seconds before the event
    moment_timestamp = max(0, event_timestamp - SECONDS_BEFORE_EVENT_FOR_VALIDATION_VIDEO)
    return SessionMomentInput(
        moment_id=event_uuid,
        timestamp_s=moment_timestamp,
        duration_s=VALIDATION_VIDEO_DURATION,
    )


@temporalio.activity.defn
async def validate_llm_single_session_summary_with_videos_activity(
    inputs: SingleSessionSummaryInputs,
) -> None:
    """Validate the LLM single session summary with videos"""
    summary_row = await database_sync_to_async(SingleSessionSummary.objects.get_summary, thread_sensitive=False)(
        team_id=inputs.team_id,
        session_id=inputs.session_id,
        extra_summary_context=inputs.extra_summary_context,
    )
    if not summary_row:
        raise ApplicationError(
            f"Summary not found in the database for session {inputs.session_id} when validating session summary with videos",
            non_retryable=True,
        )
    # Getting the user explicitly from the DB as we can't pass models between activities
    user = await database_sync_to_async(User.objects.get)(id=inputs.user_id)
    if not user:
        raise ApplicationError(
            f"User not found in the database for user {inputs.user_id} when validating session summary with videos",
            non_retryable=True,
        )
    summary_row = cast(SingleSessionSummary, summary_row)
    summary = SessionSummarySerializer(data=summary_row.summary)
    summary.is_valid(raise_exception=True)
    # Pick events to generate videos for
    events_to_validate: list[EnrichedKeyActionSerializer] = []
    for key_actions in summary.data.get("key_actions", []):
        for event in key_actions.get("events", []):
            if event.get("exception") != "blocking":
                continue
            # Keep only blocking exceptions
            validated_event = EnrichedKeyActionSerializer(data=event)
            validated_event.is_valid(raise_exception=True)
            events_to_validate.append(validated_event)
    if not events_to_validate:
        # No blocking issues detected in the summary, no need to validate
        return None
    # Generate videos for events and get asset IDs
    # TODO: Remove after testing # Temporalily limiting to one event
    events_to_validate = events_to_validate[:1]
    # Send videos to LLM for validation
    moments_analyzer = SessionMomentsLLMAnalyzer(
        session_id=inputs.session_id,
        team_id=inputs.team_id,
        user=user,
        prompt="Please summarize the video in 3 sentences.",
        failed_moments_min_ratio=FAILED_MOMENTS_MIN_RATIO,
    )
    moments_input = [
        moment
        for event in events_to_validate
        if (moment := _prepare_moment_input_from_summary_event(event, inputs.session_id))
    ]
    if not moments_input:
        raise ApplicationError(
            f"No moments input found for session {inputs.session_id} when validating session summary with videos: {events_to_validate}",
            # No sense to retry, as the events picked to validate don't have enough metadata to generate a moment
            non_retryable=True,
        )
    # TODO: 
    validation_results = await moments_analyzer.analyze(moments_input)
    print(validation_results)
    print("")