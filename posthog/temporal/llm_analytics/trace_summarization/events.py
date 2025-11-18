"""Activity for emitting trace summary events to ClickHouse."""

import json
import uuid
from datetime import UTC, datetime

import structlog
import temporalio

from posthog.models.event.util import create_event
from posthog.models.team import Team
from posthog.sync import database_sync_to_async
from posthog.temporal.llm_analytics.trace_summarization.constants import (
    EVENT_NAME_TRACE_SUMMARY,
    PROP_BATCH_RUN_ID,
    PROP_EVENT_COUNT,
    PROP_SUMMARY_BULLETS,
    PROP_SUMMARY_FLOW_DIAGRAM,
    PROP_SUMMARY_INTERESTING_NOTES,
    PROP_SUMMARY_MODE,
    PROP_SUMMARY_TEXT_REPR,
    PROP_SUMMARY_TITLE,
    PROP_TEXT_REPR_LENGTH,
    PROP_TRACE_ID,
)
from posthog.temporal.llm_analytics.trace_summarization.models import TraceSummary

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def emit_trace_summary_events_activity(
    summaries: list[TraceSummary],
    team_id: int,
    batch_run_id: str,
) -> int:
    """
    Emit $ai_trace_summary events to ClickHouse for each summary.

    These events will be used as input for embedding and clustering.
    """

    def _emit():
        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            logger.exception("Team not found", team_id=team_id)
            raise ValueError(f"Team {team_id} not found")

        count = 0
        for summary in summaries:
            event_uuid = uuid.uuid4()
            event_timestamp = datetime.now(UTC)

            properties = {
                PROP_TRACE_ID: summary.trace_id,
                PROP_BATCH_RUN_ID: batch_run_id,
                PROP_SUMMARY_MODE: summary.metadata.get("mode"),
                PROP_SUMMARY_TITLE: summary.summary.title,
                PROP_SUMMARY_TEXT_REPR: summary.text_repr,
                PROP_SUMMARY_FLOW_DIAGRAM: summary.summary.flow_diagram,
                PROP_SUMMARY_BULLETS: json.dumps([b.model_dump() for b in summary.summary.summary_bullets]),
                PROP_SUMMARY_INTERESTING_NOTES: json.dumps([n.model_dump() for n in summary.summary.interesting_notes]),
                PROP_TEXT_REPR_LENGTH: summary.metadata.get("text_repr_length"),
                PROP_EVENT_COUNT: summary.metadata.get("event_count"),
            }

            # Emit event
            create_event(
                event_uuid=event_uuid,
                event=EVENT_NAME_TRACE_SUMMARY,
                team=team,
                distinct_id=f"batch_summarization_{team_id}",
                timestamp=event_timestamp,
                properties=properties,
                person_id=None,
            )
            count += 1

        return count

    return await database_sync_to_async(_emit, thread_sensitive=False)()
