"""The tagging LLM call happens in a4; this activity only produces to Kafka."""

from datetime import timedelta

import structlog
import temporalio
from dateutil import parser as dateutil_parser

from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS
from posthog.models.event.util import format_clickhouse_timestamp
from posthog.temporal.session_replay.session_summary.state import (
    StateActivitiesEnum,
    get_data_class_from_redis,
    get_redis_state_client,
)
from posthog.temporal.session_replay.session_summary.types.video import (
    SessionTaggingOutput,
    VideoSummarySingleSessionInputs,
)

from ee.hogai.session_summaries.session.summarize_session import SingleSessionSummaryLlmInputs

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def tag_and_highlight_session_activity(
    inputs: VideoSummarySingleSessionInputs,
    tagging: SessionTaggingOutput,
) -> None:
    """Write session tags and highlight flag to ClickHouse via Kafka."""
    try:
        # Read session metadata from the same Redis cache used by A6
        redis_client, redis_input_key, _ = get_redis_state_client(
            key_base=inputs.redis_key_base,
            input_label=StateActivitiesEnum.SESSION_DB_DATA,
            state_id=inputs.session_id,
        )
        llm_input = await get_data_class_from_redis(
            redis_client=redis_client,
            redis_key=redis_input_key,
            label=StateActivitiesEnum.SESSION_DB_DATA,
            target_class=SingleSessionSummaryLlmInputs,
        )
        if not llm_input:
            logger.warning(
                f"No cached session data for session {inputs.session_id}, skipping tag write",
                session_id=inputs.session_id,
                signals_type="session-summaries",
            )
            return

        session_start_time = dateutil_parser.isoparse(llm_input.session_start_time_str)
        distinct_id = llm_input.distinct_id or ""
        _produce_to_kafka(inputs, tagging, session_start_time, distinct_id)
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
    session_start_time,
    distinct_id: str,
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
        "distinct_id": distinct_id,
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

    get_producer(topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS).produce(
        topic=KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS, data=data
    )
