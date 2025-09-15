import asyncio
from math import ceil
from typing import cast

import temporalio
from langgraph.types import RetryPolicy
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError

from posthog.constants import VIDEO_EXPORT_TASK_QUEUE
from posthog.models.exported_asset import ExportedAsset
from posthog.settings.temporal import TEMPORAL_WORKFLOW_MAX_ATTEMPTS
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs
from posthog.temporal.common.client import async_connect
from posthog.temporal.exports_video.workflow import VideoExportInputs, VideoExportWorkflow

from ee.hogai.session_summaries.constants import SECONDS_BEFORE_EVENT_FOR_VALIDATION_VIDEO, VALIDATION_VIDEO_DURATION
from ee.hogai.session_summaries.session.output_data import EnrichedKeyActionSerializer, SessionSummarySerializer
from ee.models.session_summaries import SingleSessionSummary


async def _generate_video_for_event(event: EnrichedKeyActionSerializer, inputs: SingleSessionSummaryInputs) -> None:
    """Generate a video for an event"""
    # Create ExportedAsset record for this moment
    ms_from_start = event.data.get("milliseconds_since_start")
    if ms_from_start is None:
        raise ApplicationError(
            f"Milliseconds since start not found in the event for session {inputs.session_id} when generating video for validating session summary",
            non_retryable=True,
        )
    # Start a video a couple of seconds before the event
    timestamp = max(0, ceil(ms_from_start / 1000) - SECONDS_BEFORE_EVENT_FOR_VALIDATION_VIDEO)
    moment_id = f"session-summary-moment_{inputs.session_id}_{event.data['event_uuid']}"
    exported_asset = await database_sync_to_async(ExportedAsset.objects.create)(
        team_id=inputs.team_id,
        export_format="video/mp4",
        export_context={
            "session_recording_id": inputs.session_id,
            "timestamp": timestamp,
            "filename": moment_id,
            "duration": VALIDATION_VIDEO_DURATION,
            # Keeping default values
            "mode": "screenshot",
            "css_selector": ".replayer-wrapper",
            "width": 1987,
            "height": 1312,
        },
        created_by=inputs.user_id,
    )
    # Get the Temporal client from the activity context
    client = await async_connect()
    # Start the video export workflow
    await client.start_workflow(
        VideoExportWorkflow.run,
        VideoExportInputs(exported_asset_id=exported_asset.id),
        id=f"export-video-summary_{inputs.session_id}_{event.data['event_uuid']}",
        task_queue=VIDEO_EXPORT_TASK_QUEUE,
        retry_policy=RetryPolicy(maximum_attempts=int(TEMPORAL_WORKFLOW_MAX_ATTEMPTS)),
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
    )
    # TODO: Load v


async def _generate_videos_for_events(
    events: list[EnrichedKeyActionSerializer], inputs: SingleSessionSummaryInputs
) -> None:
    """Generate videos for events"""
    tasks = {}
    async with asyncio.TaskGroup() as tg:
        for event in events:
            tasks[event.data["event_uuid"]] = tg.create_task(_generate_video_for_event(event, inputs))
    for task in tasks.items():
        await task


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
            f"Session summary not found in the database for session {inputs.session_id} when validating with videos",
            non_retryable=True,
        )
    summary_row = cast(SingleSessionSummary, summary_row)
    summary = SessionSummarySerializer(data=summary_row.summary)
    # Pick events to generate videos for
    events_to_validate: list[EnrichedKeyActionSerializer] = []
    for key_actions in summary.data.get("key_actions", []):
        for event in key_actions.get("events", []):
            if event.get("exception") != "blocking":
                continue
            # Keep only blocking exceptions
            events_to_validate.append(cast(EnrichedKeyActionSerializer, event))
    # Generate videos for events
    await _generate_videos_for_events(events_to_validate, inputs)
