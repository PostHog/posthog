"""
Activity 5 of the video-based summarization workflow:
Embedding the meaningful video segments and storing them in ClickHouse.
(Python modules have to start with a letter, hence the file is prefixed `a5_` instead of `5_`.)
"""

import structlog
import temporalio

from posthog.schema import EmbeddingModelName

from posthog.api.embedding_worker import emit_embedding_request
from posthog.models.team.team import Team
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.sync import database_sync_to_async
from posthog.temporal.ai.session_summary.types.video import VideoSegmentOutput, VideoSummarySingleSessionInputs

SESSION_SEGMENTS_EMBEDDING_MODEL = EmbeddingModelName.TEXT_EMBEDDING_3_LARGE_3072

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def embed_and_store_segments_activity(
    inputs: VideoSummarySingleSessionInputs,
    segments: list[VideoSegmentOutput],
) -> None:
    """Generate embeddings for all segments and produce to Kafka for ClickHouse storage

    Each segment description is embedded with metadata including session_id, team_id,
    distinct_id, and timestamps.
    """
    if not segments:
        return
    team = await Team.objects.aget(id=inputs.team_id)
    session_metadata = await database_sync_to_async(
        SessionReplayEvents().get_metadata
    )(
        session_id=inputs.session_id,
        team=team,  # TODO: get_metadata actually only uses team_id – we should refactor it to avoid pointless Team lookup
    )
    if not session_metadata:
        logger.error(f"Session metadata not found for session {inputs.session_id}", session_id=inputs.session_id)
        return
    try:
        for segment in segments:
            # Use the description directly as the content to embed
            content = segment.description

            # Create unique document ID
            document_id = f"{inputs.session_id}:{segment.start_time}:{segment.end_time}"

            # Include structured metadata for querying/filtering
            metadata = {
                "session_id": inputs.session_id,
                "team_id": inputs.team_id,
                "distinct_id": inputs.user_distinct_id_to_log,
                "start_time": segment.start_time,
                "end_time": segment.end_time,
                "session_start_time": session_metadata["start_time"].isoformat(),
                "session_end_time": session_metadata["end_time"].isoformat(),
                "session_duration": session_metadata["duration"],
                "session_active_seconds": session_metadata["active_seconds"],
            }

            emit_embedding_request(
                team_id=inputs.team_id,
                product="session-replay",
                document_type="video-segment",
                rendering="video-analysis",
                document_id=document_id,
                content=content,
                models=[SESSION_SEGMENTS_EMBEDDING_MODEL.value],
                metadata=metadata,
            )

            logger.debug(
                f"Produced embedding for segment {document_id}",
                session_id=inputs.session_id,
                document_id=document_id,
                signals_type="session-summaries",
            )

        logger.debug(
            f"Successfully produced {len(segments)} embeddings for session {inputs.session_id}",
            session_id=inputs.session_id,
            segment_count=len(segments),
            signals_type="session-summaries",
        )

    except Exception as e:
        logger.exception(
            f"Failed to embed and store segments for session {inputs.session_id}: {e}",
            session_id=inputs.session_id,
            signals_type="session-summaries",
        )
        raise
