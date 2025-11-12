from dataclasses import asdict
from typing import Any, cast

import temporalio
from temporalio.exceptions import ApplicationError

from posthog.models.user import User
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs

from ee.hogai.session_summaries.session.output_data import SessionSummarySerializer
from ee.hogai.session_summaries.session.video_validation import SessionSummaryVideoValidator
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
    # If the summary was already validated with videos, return
    run_metadata = cast(dict[str, Any], summary_row.run_metadata)
    if run_metadata and run_metadata.get("visual_confirmation"):
        # Summary was already validated with videos, return
        return None
    # Getting the user explicitly from the DB as we can't pass models between activities
    try:
        user = await User.objects.aget(id=inputs.user_id)
    except User.DoesNotExist:
        raise ApplicationError(
            f"User not found in the database for user {inputs.user_id} when validating session summary with videos",
            non_retryable=True,
        )
    summary = SessionSummarySerializer(data=summary_row.summary)
    summary.is_valid(raise_exception=True)
    # Validate the session summary with videos
    video_validator = SessionSummaryVideoValidator(
        session_id=inputs.session_id,
        summary=summary,
        run_metadata=run_metadata,
        team_id=inputs.team_id,
        user=user,
        trace_id=temporalio.activity.info().workflow_id,
    )
    video_validation_result = await video_validator.validate_session_summary_with_videos(
        model_to_use=inputs.model_to_use
    )
    if video_validation_result is None:
        # No video validation result, don't try to update the summary
        return None
    updated_summary, updated_run_metadata = video_validation_result
    # Store the updated summary in the database
    summary_row.summary = updated_summary.data
    summary_row.run_metadata = asdict(updated_run_metadata)
    # Each summary is generated only once and then reused, so probability of race conditions is low, and transactions are not needed
    # It could be possible if multiple people summarize the same session at the same time, but I don't expect it to happen often
    await summary_row.asave(update_fields=["summary", "run_metadata"])
