import json
from dataclasses import asdict
from math import ceil
from typing import cast
import yaml

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
from ee.hogai.session_summaries.session.summarize_session import generate_video_description_prompt
from ee.hogai.videos.session_moments import SessionMomentInput, SessionMomentsLLMAnalyzer
from ee.models.session_summaries import SingleSessionSummary


def _prepare_moment_input_from_summary_event(
    prompt: str, event: EnrichedKeyActionSerializer, session_id: str
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
        prompt=prompt,
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
    with open(f"summary_{inputs.session_id}.json", "w") as f:
        json.dump(summary_row.summary, f, indent=4)
    summary = SessionSummarySerializer(data=summary_row.summary)
    summary.is_valid(raise_exception=True)
    # Pick blocking exceptions to generate videos for
    events_to_validate: list[tuple[str, EnrichedKeyActionSerializer]] = []
    # Keep track of the blocks that would need an update based on the video-based results
    fields_to_update: dict[str, str] = {}
    for ki, key_actions in enumerate(summary.data.get("key_actions", [])):
        segment_index = key_actions["segment_index"]
        for ei, event in enumerate(key_actions.get("events", [])):
            if event.get("exception") != "blocking":
                continue
            # Keep only blocking exceptions
            validated_event = EnrichedKeyActionSerializer(data=event)
            validated_event.is_valid(raise_exception=True)
            # Collect the fields to validate/update and their current values
            # Current event fields
            for field in ["description", "exception", "abandonment", "confusion"]:
                field_path = f"key_actions[{ki}].events[{ei}].{field}"
                # TODO: Use dataclasses, avoid code repetition
                fields_to_update[field_path] = {
                    "path": field_path,
                    "current_value": event[field],
                    "new_value": None,
                }
            # Related segment outcome
            for field in ["success", "summary"]:
                field_path = f"segment_outcomes[{segment_index}].{field}"
                fields_to_update[field_path] = {
                    "path": field_path,
                    "current_value": summary.data["segment_outcomes"][segment_index][field],
                    "new_value": None,
                }
            field_path = f"segments[{segment_index}].name"
            fields_to_update[field_path] = {
                "path": field_path,
                "current_value": summary.data["segments"][segment_index]["name"],
                "new_value": None,
            }
            # Session outcome
            for field in ["success", "description"]:
                field_path = f"session_outcome.{field}"
                fields_to_update[field_path] = {
                    "path": field_path,
                    "current_value": summary.data["session_outcome"][field],
                    "new_value": None,
                }
            # Generate prompt
            prompt = generate_video_description_prompt(event=validated_event)
            events_to_validate.append((prompt, validated_event))
    if not events_to_validate:
        # No blocking issues detected in the summary, no need to validate
        return None
    # Sort fields to update by path
    fields_to_update = dict(sorted(fields_to_update.items(), key=lambda x: x[0]))
    with open(f"fields_to_update_{inputs.session_id}.yml", "w") as f:
        yaml.dump(list(fields_to_update.values()), f, allow_unicode=True, sort_keys=False)

    # Pick events that happened before/after the exception, if they fit within the video duration
    # TODO: Decide if I need it
    # events_context: dict[str, dict[str, list[EnrichedKeyActionSerializer]]] = {}
    # for etv in events_to_validate:
    #     events_context[etv.data["event_uuid"]] = {
    #         "before": [],
    #         "after": [],
    #     }
    #     etv_timestamp = etv.data.get("milliseconds_since_start")
    #     if etv_timestamp is None:
    #         # No context available
    #         continue
    #     # Don't want to go negative
    #     etv_from_timestamp = max(0, etv_timestamp - SECONDS_BEFORE_EVENT_FOR_VALIDATION_VIDEO*1000)
    #     etv_to_timestamp = etv_timestamp + VALIDATION_VIDEO_DURATION*1000
    #     for event in summary.data.get("key_actions", []):
    #         if event.get("event_uuid") == etv.data["event_uuid"]:
    #             continue
    #         event_timestamp = event.get("milliseconds_since_start")
    #         if event_timestamp is None:
    #             continue
    #         if event_timestamp >= etv_from_timestamp and event_timestamp <= etv_timestamp:
    #             events_context[etv.data["event_uuid"]]["before"].append(event)
    #         elif event_timestamp >= etv_timestamp and event_timestamp <= etv_to_timestamp:
    #             events_context[etv.data["event_uuid"]]["after"].append(event)

    # Prepare input for video validation
    moments_analyzer = SessionMomentsLLMAnalyzer(
        session_id=inputs.session_id,
        team_id=inputs.team_id,
        user=user,
        failed_moments_min_ratio=FAILED_MOMENTS_MIN_RATIO,
    )
    moments_input = [
        moment
        for prompt, event in events_to_validate
        if (
            moment := _prepare_moment_input_from_summary_event(prompt=prompt, event=event, session_id=inputs.session_id)
        )
    ]
    with open(f"moments_input_{inputs.session_id}.json", "w") as f:
        json.dump([asdict(x) for x in moments_input], f, indent=4)
    if not moments_input:
        raise ApplicationError(
            f"No moments input found for session {inputs.session_id} when validating session summary with videos: {events_to_validate}",
            # No sense to retry, as the events picked to validate don't have enough metadata to generate a moment
            non_retryable=True,
        )
    # Generate videos and asks LLM to describe them
    description_results = await moments_analyzer.analyze(moments_input=moments_input)
    with open(f"validation_results_{inputs.session_id}.json", "w") as f:
        json.dump(description_results, f, indent=4)
    # TODO: Update the summary with the description results
