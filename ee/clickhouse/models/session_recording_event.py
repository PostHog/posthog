import datetime
import json
import uuid
from typing import Union

import structlog
from sentry_sdk import capture_exception

from ee.clickhouse.models.util import cast_timestamp_or_now
from ee.clickhouse.sql.session_recording_events import INSERT_SESSION_RECORDING_EVENT_SQL
from ee.kafka_client.client import ClickhouseProducer
from ee.kafka_client.topics import KAFKA_SESSION_RECORDING_EVENTS
from posthog.client import sync_execute

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
