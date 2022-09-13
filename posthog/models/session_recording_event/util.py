import datetime
import json
import uuid
from typing import Union

import structlog
from django.utils import timezone
from sentry_sdk import capture_exception

from posthog.client import sync_execute
from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_SESSION_RECORDING_EVENTS
from posthog.models.session_recording_event.sql import INSERT_SESSION_RECORDING_EVENT_SQL
from posthog.utils import cast_timestamp_or_now

logger = structlog.get_logger(__name__)

MAX_KAFKA_MESSAGE_LENGTH = 800_000
MAX_INSERT_LENGTH = 15_000_000


def create_session_recording_event(
    uuid: uuid.UUID,
    team_id: int,
    distinct_id: str,
    session_id: str,
    window_id: str,
    timestamp: Union[datetime.datetime, str],
    snapshot_data: dict,
) -> str:
    timestamp = cast_timestamp_or_now(timestamp)
    snapshot_data_json = json.dumps(snapshot_data)
    data = {
        "uuid": str(uuid),
        "team_id": team_id,
        "distinct_id": distinct_id,
        "session_id": session_id,
        "window_id": window_id,
        "snapshot_data": snapshot_data_json,
        "events_summary": "",
        "timestamp": timestamp,
        "created_at": timestamp,
    }
    if len(snapshot_data_json) <= MAX_KAFKA_MESSAGE_LENGTH:
        p = ClickhouseProducer()
        p.produce(sql=INSERT_SESSION_RECORDING_EVENT_SQL(), topic=KAFKA_SESSION_RECORDING_EVENTS, data=data)
    elif len(snapshot_data_json) <= MAX_INSERT_LENGTH:
        sync_execute(INSERT_SESSION_RECORDING_EVENT_SQL(), data, settings={"max_query_size": MAX_INSERT_LENGTH})
    else:
        capture_exception(Exception(f"Session recording event data too large - {len(snapshot_data_json)}"))

    return str(uuid)


def get_recording_count_for_team_and_period(
    team_id: Union[str, int], begin: timezone.datetime, end: timezone.datetime
) -> int:
    result = sync_execute(
        """
        SELECT count(distinct session_id) as count
        FROM session_recording_events
        WHERE team_id = %(team_id)s
        AND timestamp between %(begin)s AND %(end)s
    """,
        {"team_id": str(team_id), "begin": begin, "end": end},
    )[0][0]
    return result
