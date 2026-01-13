"""
Activity 1 of the video segment clustering workflow:
Prime session embeddings by fetching recent sessions and running summarization.
"""

from django.conf import settings

import structlog
from temporalio import activity

from posthog.models.team import Team
from posthog.models.user import User
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.summarize_session import SummarizeSingleSessionWorkflow
from posthog.temporal.ai.session_summary.types.single import SingleSessionSummaryInputs
from posthog.temporal.ai.video_segment_clustering import constants
from posthog.temporal.ai.video_segment_clustering.data import fetch_recent_session_ids
from posthog.temporal.ai.video_segment_clustering.models import (
    PrimeSessionEmbeddingsActivityInputs,
    PrimeSessionEmbeddingsResult,
)
from posthog.temporal.common.client import async_connect

from ee.hogai.session_summaries.constants import DEFAULT_VIDEO_UNDERSTANDING_MODEL
from ee.models.session_summaries import SingleSessionSummary

logger = structlog.get_logger(__name__)


async def _prime_session_embeddings(inputs: PrimeSessionEmbeddingsActivityInputs) -> PrimeSessionEmbeddingsResult:
    """Fetch recent sessions and run summarization workflows to prime embeddings table."""
    team = await Team.objects.aget(id=inputs.team_id)

    # Step 1: Fetch recent session IDs
    session_ids = await database_sync_to_async(fetch_recent_session_ids)(
        team=team,
        lookback_hours=inputs.lookback_hours,
    )

    if not session_ids:
        return PrimeSessionEmbeddingsResult(
            session_ids_found=0,
            sessions_summarized=0,
            sessions_skipped=0,
            sessions_failed=0,
        )

    # Step 2: Get system user for running summarization
    system_user = await User.objects.filter(is_active=True, is_staff=True).afirst()
    if not system_user:
        system_user = await User.objects.filter(is_active=True).afirst()

    if not system_user:
        logger.warning("No user found to run summarization", team_id=inputs.team_id)
        return PrimeSessionEmbeddingsResult(
            session_ids_found=len(session_ids),
            sessions_summarized=0,
            sessions_skipped=len(session_ids),
            sessions_failed=0,
        )

    # Step 3: Check which sessions already have summaries
    existing_summaries = await database_sync_to_async(SingleSessionSummary.objects.summaries_exist)(
        team_id=inputs.team_id,
        session_ids=session_ids,
        extra_summary_context=None,
    )

    client = await async_connect()

    sessions_summarized = 0
    sessions_failed = 0
    sessions_skipped = 0

    # Step 4: Start summarization workflows for sessions without summaries
    handles = []
    for session_id in session_ids:
        if existing_summaries.get(session_id):
            sessions_skipped += 1
            logger.info("Session summary already exists, skipping", session_id=session_id)
            continue

        try:
            redis_key_base = f"session-summary:clustering:{team.id}:{session_id}"
            workflow_input = SingleSessionSummaryInputs(
                session_id=session_id,
                user_id=system_user.id,
                user_distinct_id_to_log=system_user.distinct_id,
                team_id=team.id,
                redis_key_base=redis_key_base,
                model_to_use=DEFAULT_VIDEO_UNDERSTANDING_MODEL,
                video_validation_enabled="full",
            )

            handle = await client.start_workflow(
                SummarizeSingleSessionWorkflow.run,
                workflow_input,
                id=f"session-summary-clustering-{team.id}-{session_id}",
                task_queue=settings.MAX_AI_TASK_QUEUE,
                execution_timeout=constants.SUMMARIZE_SESSIONS_ACTIVITY_TIMEOUT,
            )
            handles.append((session_id, handle))
        except Exception as e:
            if "already started" in str(e).lower() or "already exists" in str(e).lower():
                sessions_skipped += 1
                logger.info("Session summarization already running", session_id=session_id)
            else:
                sessions_failed += 1
                logger.warning("Failed to start summarization workflow", session_id=session_id, error=str(e))

    # Step 5: Wait for all workflows to complete
    for session_id, handle in handles:
        try:
            await handle.result()
            sessions_summarized += 1
            logger.info("Session summarization completed", session_id=session_id)
        except Exception as e:
            if "already started" in str(e).lower():
                sessions_skipped += 1
            else:
                sessions_failed += 1
                logger.warning("Session summarization failed", session_id=session_id, error=str(e))

    return PrimeSessionEmbeddingsResult(
        session_ids_found=len(session_ids),
        sessions_summarized=sessions_summarized,
        sessions_skipped=sessions_skipped,
        sessions_failed=sessions_failed,
    )


@activity.defn
async def prime_session_embeddings_activity(
    inputs: PrimeSessionEmbeddingsActivityInputs,
) -> PrimeSessionEmbeddingsResult:
    """Prime the document_embeddings table by running session summarization.

    Fetches recent sessions that ended within the lookback period and runs
    video-based summarization to populate embeddings for clustering.
    """
    return await _prime_session_embeddings(inputs)
