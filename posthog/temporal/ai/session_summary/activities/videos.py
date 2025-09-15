import asyncio
from math import ceil
from typing import cast, Optional
import uuid

import temporalio
from temporalio.common import RetryPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import ApplicationError

from posthog.constants import VIDEO_EXPORT_TASK_QUEUE
from posthog.models.exported_asset import ExportedAsset
from posthog.models.user import User
from posthog.settings.temporal import TEMPORAL_WORKFLOW_MAX_ATTEMPTS
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs
from posthog.temporal.common.client import async_connect
from posthog.temporal.exports_video.workflow import VideoExportInputs, VideoExportWorkflow
from posthog.storage import object_storage

from ee.hogai.session_summaries.constants import SECONDS_BEFORE_EVENT_FOR_VALIDATION_VIDEO, VALIDATION_VIDEO_DURATION
from ee.hogai.session_summaries.session.output_data import EnrichedKeyActionSerializer, SessionSummarySerializer
from ee.models.session_summaries import SingleSessionSummary


async def _generate_video_for_event(
    event: EnrichedKeyActionSerializer, inputs: SingleSessionSummaryInputs, user: User
) -> int:
    """Generate a video for an event and return the asset ID"""
    # Create ExportedAsset record for this moment (TODO: move comment)
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
        created_by=user,
    )
    # Generate a video
    client = await async_connect()
    await client.execute_workflow(
        VideoExportWorkflow.run,
        VideoExportInputs(exported_asset_id=exported_asset.id),
        # TODO: Check why multiple workflow could be started with the same id
        id=f"export-video-summary_{inputs.session_id}_{event.data['event_uuid']}_{uuid.uuid4()}",
        task_queue=VIDEO_EXPORT_TASK_QUEUE,
        retry_policy=RetryPolicy(maximum_attempts=int(TEMPORAL_WORKFLOW_MAX_ATTEMPTS)),
        id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
    )
    # Return the asset ID for later retrieval
    return exported_asset.id


async def _generate_videos_for_events(
    events: list[EnrichedKeyActionSerializer], inputs: SingleSessionSummaryInputs, user: User
) -> dict[str, int]:
    """Generate videos for events and return mapping of event_uuid to asset_id"""
    tasks = {}
    async with asyncio.TaskGroup() as tg:
        for event in events:
            tasks[event.data["event_uuid"]] = tg.create_task(_generate_video_for_event(event, inputs, user))
    # Collect results - asset IDs
    asset_ids = {}
    for event_uuid, task in tasks.items():
        asset_ids[event_uuid] = await task
    return asset_ids


async def get_video_bytes(asset_id: int) -> Optional[bytes]:
    """Retrieve video content as bytes for an ExportedAsset ID"""
    try:
        # Fetch the asset from the database
        asset = await database_sync_to_async(ExportedAsset.objects.get)(id=asset_id)

        # Get content from either database or object storage
        if asset.content:
            # Content stored directly in database
            return bytes(asset.content)
        elif asset.content_location:
            # Content stored in object storage
            return await database_sync_to_async(object_storage.read_bytes)(asset.content_location)
        else:
            return None
    except ExportedAsset.DoesNotExist:
        return None


async def send_videos_to_llm(asset_ids: dict[str, int], inputs: SingleSessionSummaryInputs) -> dict[str, str]:
    """Send videos to LLM for validation and get analysis results"""
    from google import genai

    # Example implementation - adjust based on your LLM client
    results = {}

    for event_uuid, asset_id in asset_ids.items():
        video_bytes = await get_video_bytes(asset_id)
        if video_bytes and len(video_bytes) < 20 * 1024 * 1024:  # 20MB limit
            # TODO: Remove after testing, storing for debugging
            with open(f"video_{event_uuid}.mp4", "wb") as f:
                f.write(video_bytes)
            # Send to your LLM here
            client = genai.Client()
            response = client.models.generate_content(
                model="models/gemini-2.5-flash",
                contents=genai.types.Content(
                    parts=[
                        genai.types.Part(inline_data=genai.types.Blob(data=video_bytes, mime_type="video/mp4")),
                        genai.types.Part(text="Please summarize the video in 3 sentences."),
                    ]
                ),
            )
            results[event_uuid] = response.text

    return results


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
    # TODO: Remove after testing
    # Temporalily limiting to one event
    events_to_validate = events_to_validate[:1]
    asset_ids = await _generate_videos_for_events(events_to_validate, inputs, user)
    # Send videos to LLM for validation
    validation_results = await send_videos_to_llm(asset_ids, inputs)
    # TODO: Process validation results and update summary if needed
    for event_uuid, result in validation_results.items():
        print(f"Event {event_uuid}: {result}")
