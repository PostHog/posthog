import json
from typing import cast

import temporalio
from temporalio.exceptions import ApplicationError

from posthog.models.user import User
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs

from ee.models.session_summaries import SingleSessionSummary


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
        json.dump(summary_row.summary, f, indent=4, sort_keys=True)

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
