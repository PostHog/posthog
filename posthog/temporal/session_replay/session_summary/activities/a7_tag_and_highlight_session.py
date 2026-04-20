"""
Activity 7 of the video-based summarization workflow:
Write session tags and highlight flag to ClickHouse via Kafka (fire-and-forget).

The tagging LLM call happens in A4 as a follow-up turn in the same conversation
that produced the consolidation. This activity only handles the Kafka produce.
"""

from datetime import datetime, timedelta

import structlog
import temporalio

from posthog.kafka_client.client import KafkaProducer
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.models.team.team import Team
from posthog.session_recordings.queries.session_replay_events import SessionReplayEvents
from posthog.sync import database_sync_to_async
from posthog.temporal.session_replay.session_summary.types.video import (
    SessionTaggingOutput,
    VideoSummarySingleSessionInputs,
)

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def tag_and_highlight_session_activity(
    inputs: VideoSummarySingleSessionInputs,
    tagging: SessionTaggingOutput,
) -> None:
    """Write session tags and highlight flag to ClickHouse via Kafka."""
    try:
        team = await Team.objects.aget(id=inputs.team_id)
        metadata = await database_sync_to_async(SessionReplayEvents().get_metadata, thread_sensitive=False)(
            session_id=inputs.session_id,
            team=team,
        )
        if not metadata or not metadata.get("start_time"):
            logger.warning(
                f"No metadata for session {inputs.session_id}, skipping tag write",
                session_id=inputs.session_id,
                signals_type="session-summaries",
            )
            return
        _produce_to_kafka(inputs, tagging, metadata["start_time"])
    except Exception:
        logger.exception(
            f"Failed to write tags to Kafka for session {inputs.session_id}",
            session_id=inputs.session_id,
            signals_type="session-summaries",
        )
        raise


def _produce_to_kafka(
    inputs: VideoSummarySingleSessionInputs,
    tagging: SessionTaggingOutput,
    session_start_time: datetime,
) -> None:
    """Produce a Kafka message to write tags and highlight flag to ClickHouse.

    All non-tagging fields use identity values for their aggregate functions
    so they don't affect existing data:
    - Timestamps use session_start + 1µs so min/max/argMin all keep real values
      (using now() previously poisoned max_last_timestamp)
    - block_url is None so groupArray drops it (empty string previously
      polluted block_urls and broke the length-match check in listBlocks)
    - sum() fields use 0, any() fields use empty string
    """
    tag_row_ts = format_clickhouse_timestamp(session_start_time + timedelta(microseconds=1))
    data = {
        "session_id": inputs.session_id,
        "team_id": inputs.team_id,
        "distinct_id": "",
        "first_timestamp": tag_row_ts,
        "last_timestamp": tag_row_ts,
        "block_url": None,
        "first_url": None,
        "urls": [],
        "click_count": 0,
        "keypress_count": 0,
        "mouse_activity_count": 0,
        "active_milliseconds": 0,
        "console_log_count": 0,
        "console_warn_count": 0,
        "console_error_count": 0,
        "size": 0,
        "event_count": 0,
        "message_count": 0,
        "snapshot_source": None,
        "snapshot_library": None,
        "retention_period_days": None,
        "is_deleted": 0,
        "ai_tags_fixed": list(tagging.tags_fixed),
        "ai_tags_freeform": list(tagging.tags_freeform),
        "ai_highlighted": int(tagging.highlighted),
    }

    producer = KafkaProducer()
    producer.produce(topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS, data=data)
