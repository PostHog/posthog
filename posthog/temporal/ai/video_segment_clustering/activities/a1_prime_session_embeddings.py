"""
Activity 1 of the video segment clustering workflow:
Prime session embeddings by fetching recent sessions and running summarization.
"""

import asyncio

import structlog
from temporalio import activity

from posthog.schema import PropertyOperator, RecordingPropertyFilter, RecordingsQuery

from posthog.clickhouse.query_tagging import Product, tags_context
from posthog.models.team import Team
from posthog.session_recordings.queries.session_recording_list_from_query import SessionRecordingListFromQuery
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.summarize_session import execute_summarize_session
from posthog.temporal.ai.video_segment_clustering.models import (
    PrimeSessionEmbeddingsActivityInputs,
    PrimeSessionEmbeddingsResult,
)

from ee.hogai.session_summaries.constants import MIN_SESSION_DURATION_FOR_SUMMARY_MS
from ee.models.session_summaries import SingleSessionSummary

logger = structlog.get_logger(__name__)


@activity.defn
async def prime_session_embeddings_activity(
    inputs: PrimeSessionEmbeddingsActivityInputs,
) -> PrimeSessionEmbeddingsResult:
    """Prime the document_embeddings table by running session summarization.

    Fetches recent sessions that ended within the lookback period and runs video-based summarization
    to populate session segment embeddings for clustering.

    This is pretty crude, as it means we're summarizing EVERY session in the lookback period - but okay for small teams.
    """
    team = await Team.objects.aget(id=inputs.team_id)

    session_ids = await database_sync_to_async(_fetch_recent_session_ids)(
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

    # Get first user with access to the team for running summarization (as summarization requires _some_ user)
    # TODO: We should instead pass no user, in which case summarization should understand this was system-initiated
    system_user = await database_sync_to_async(lambda: team.all_users_with_access().first())()

    if not system_user:
        logger.warning("No user found to run summarization", team_id=inputs.team_id)
        return PrimeSessionEmbeddingsResult(
            session_ids_found=len(session_ids),
            sessions_summarized=0,
            sessions_skipped=len(session_ids),
            sessions_failed=0,
        )

    # Check which sessions already have summaries
    existing_summaries = await database_sync_to_async(SingleSessionSummary.objects.summaries_exist)(
        team_id=inputs.team_id,
        session_ids=session_ids,
        extra_summary_context=None,
    )

    sessions_summarized = 0
    sessions_failed = 0
    sessions_skipped = 0

    # Start summarization workflows for sessions without summaries
    sessions_to_summarize = [session_id for session_id in session_ids if not existing_summaries.get(session_id)]
    if sessions_to_summarize:
        results = await asyncio.gather(
            *[
                execute_summarize_session(
                    session_id=session_id,
                    user=system_user,
                    team=team,
                    video_validation_enabled="full",
                )
                for session_id in sessions_to_summarize
            ],
            return_exceptions=True,
        )
        for session_id, result in zip(sessions_to_summarize, results):
            if isinstance(result, Exception):
                sessions_failed += 1
                logger.error("Session summarization failed", session_id=session_id, error=str(result))
            else:
                sessions_summarized += 1

    return PrimeSessionEmbeddingsResult(
        session_ids_found=len(session_ids),
        sessions_summarized=sessions_summarized,
        sessions_skipped=sessions_skipped,
        sessions_failed=sessions_failed,
    )


def _fetch_recent_session_ids(team: Team, lookback_hours: int) -> list[str]:
    """Fetch session IDs of recordings that ended within the lookback period.

    Args:
        team: Team object to query for
        lookback_hours: How far back to look for ended recordings

    Returns:
        List of session IDs of finished recordings in the timeframe
    """
    # RecordingsQuery for consistency with the session recordings API
    query = RecordingsQuery(
        filter_test_accounts=True,
        date_from=f"-{lookback_hours}h",
        having_predicates=[
            RecordingPropertyFilter(
                key="duration",  # Ignore sessions that are too short
                operator=PropertyOperator.GTE,
                value=MIN_SESSION_DURATION_FOR_SUMMARY_MS / 1000,
            ),
            RecordingPropertyFilter(
                key="ongoing",  # Only include finished sessions
                operator=PropertyOperator.EXACT,
                value=0,  # The bool is represented as 0/1 in ClickiHouse
            ),
        ],
    )

    with tags_context(product=Product.SESSION_SUMMARY):
        result = SessionRecordingListFromQuery(team=team, query=query).run()

    return [recording["session_id"] for recording in result.results]
