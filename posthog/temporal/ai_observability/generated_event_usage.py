import json
import uuid
import hashlib
from typing import Any

from django.utils import timezone

import structlog
from confluent_kafka import KafkaException

from posthog.models.event.util import create_event
from posthog.models.team import Team
from posthog.usage_ingestion.client import UsageRecord, report_usage

PRODUCER_ID = "ai-observability"
AI_EVENTS_USAGE_KEY = "ai_events"
EVENT_DELIVERY_TIMEOUT_SECONDS = 2.0

logger = structlog.get_logger(__name__)


def create_generated_ai_event(
    *,
    event_uuid: uuid.UUID,
    event: str,
    team: Team,
    distinct_id: str,
    properties: dict[str, Any],
) -> None:
    """Write an AI event that PostHog generates in the team's project, and report its usage after Kafka acknowledges it.

    These events go straight to ClickHouse, so they skip the ingestion pipeline that writes the
    usage record for every other AI event. The nightly report counts them as AI events, so they
    need their own record here.
    """
    timestamp = timezone.now()
    try:
        create_event(
            event_uuid=event_uuid,
            event=event,
            team=team,
            distinct_id=distinct_id,
            timestamp=timestamp,
            properties=properties,
            delivery_timeout_seconds=EVENT_DELIVERY_TIMEOUT_SECONDS,
        )
    except (KafkaException, TimeoutError):
        # Usage counts only the events that Kafka acknowledged, as ingestion does. The error does not
        # fail the activity, because a retry repeats the work that produced the event.
        logger.warning("generated_ai_event_not_delivered", ai_event=event, team_id=team.id, exc_info=True)
        return
    report_usage(
        [
            UsageRecord(
                record_id=_record_id(timestamp.date().isoformat(), event, distinct_id, event_uuid),
                producer_id=PRODUCER_ID,
                team_id=team.id,
                usage_key=AI_EVENTS_USAGE_KEY,
                unit="events",
                quantity=1,
                timestamp_ms=int(timestamp.timestamp() * 1000),
            )
        ],
        site="ai_observability_generated_event",
    )


def _record_id(day: str, event: str, distinct_id: str, event_uuid: uuid.UUID) -> str:
    # The same identity as the ingestion pipeline's records (`analyticsRecordId` in
    # nodejs/src/ingestion/common/steps/usage-records-steps.ts): the event's day, then a hash of
    # the event name, distinct ID and UUID.
    identity = json.dumps([event, distinct_id, str(event_uuid)], separators=(",", ":"), ensure_ascii=False)
    return f"{day}:{hashlib.sha256(identity.encode()).hexdigest()[:32]}"
