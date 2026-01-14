"""
Activity 1 of the video segment clustering workflow:
Prime session embeddings by fetching recent sessions and running summarization.
"""

import asyncio

import structlog
from temporalio import activity

from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.summarize_session import execute_summarize_session
from posthog.temporal.ai.video_segment_clustering.data import fetch_recent_session_ids
from posthog.temporal.ai.video_segment_clustering.models import (
    PrimeSessionEmbeddingsActivityInputs,
    PrimeSessionEmbeddingsResult,
)

from ee.hogai.session_summaries.constants import DEFAULT_VIDEO_UNDERSTANDING_MODEL
from ee.models.session_summaries import SingleSessionSummary

logger = structlog.get_logger(__name__)


async def _prime_session_embeddings(inputs: PrimeSessionEmbeddingsActivityInputs) -> PrimeSessionEmbeddingsResult:
    """
    Fetch recent sessions and run summarization workflows to prime embeddings table.

    This is pretty crude, as it means we're summarizing EVERY session in the lookback period - but okay for small teams.
    """
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

    # Step 2: Get first user with access to the team for running summarization (as summarization requires _some_ user)
    system_user = await database_sync_to_async(lambda: team.all_users_with_access().first())()

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

    sessions_summarized = 0
    sessions_failed = 0
    sessions_skipped = 0

    # Step 4: Start summarization workflows for sessions without summaries
    sessions_to_summarize = [session_id for session_id in session_ids if not existing_summaries.get(session_id)]
    if sessions_to_summarize:
        results = await asyncio.gather(
            *[
                execute_summarize_session(
                    session_id=session_id,
                    user=system_user,
                    team=team,
                    model_to_use=DEFAULT_VIDEO_UNDERSTANDING_MODEL,
                    extra_summary_context=None,
                    local_reads_prod=False,
                    video_validation_enabled="full",
                )
                for session_id in sessions_to_summarize
            ],
            return_exceptions=True,
        )
        for session_id, result in zip(sessions_to_summarize, results):
            if isinstance(result, Exception):
                sessions_failed += 1
                logger.warning("Session summarization failed", session_id=session_id, error=str(result))
            else:
                sessions_summarized += 1
                logger.info("Session summarization completed", session_id=session_id)

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
