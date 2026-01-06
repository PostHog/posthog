import structlog
import temporalio

from posthog.schema import EmbeddingModelName

from posthog.api.embedding_worker import emit_embedding_request
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
    try:
        if not segments:
            logger.info(
                f"No segments to embed for session {inputs.session_id}",
                session_id=inputs.session_id,
            )
            return

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
            )

        logger.info(
            f"Successfully produced {len(segments)} embeddings for session {inputs.session_id}",
            session_id=inputs.session_id,
            segment_count=len(segments),
        )

    except Exception as e:
        logger.exception(
            f"Failed to embed and store segments for session {inputs.session_id}: {e}",
            session_id=inputs.session_id,
        )
        raise
