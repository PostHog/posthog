import json
from datetime import datetime
from typing import Optional
from uuid import uuid4

import structlog

from posthog.client import sync_execute
from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS
from posthog.session_recordings.sql.session_recording_event_sql import INSERT_SESSION_RECORDING_EVENT_SQL
from posthog.session_recordings.queries.test.session_replay_sql import produce_replay_summary
from posthog.utils import cast_timestamp_or_now

logger = structlog.get_logger(__name__)

MAX_KAFKA_MESSAGE_LENGTH = 800_000
MAX_INSERT_LENGTH = 15_000_000


def _insert_session_recording_event(
    team_id: int,
    distinct_id: str,
    session_id: str,
    window_id: str,
    timestamp: datetime,
    snapshot_data: dict,
) -> str:
    uuid = uuid4()
    snapshot_data_json = json.dumps(snapshot_data)
    timestamp_str = cast_timestamp_or_now(timestamp)
    data = {
        "uuid": str(uuid),
        "team_id": team_id,
        "distinct_id": distinct_id,
        "session_id": session_id,
        "window_id": window_id,
        "snapshot_data": snapshot_data_json,
        "timestamp": timestamp_str,
        "created_at": timestamp_str,
    }
    if len(snapshot_data_json) <= MAX_KAFKA_MESSAGE_LENGTH:
        p = ClickhouseProducer()
        p.produce(sql=INSERT_SESSION_RECORDING_EVENT_SQL(), topic=KAFKA_CLICKHOUSE_SESSION_RECORDING_EVENTS, data=data)
    elif len(snapshot_data_json) <= MAX_INSERT_LENGTH:
        sync_execute(INSERT_SESSION_RECORDING_EVENT_SQL(), data, settings={"max_query_size": MAX_INSERT_LENGTH})

    return str(uuid)


def create_session_recording_events(
    team_id: int,
    timestamp: datetime,
    distinct_id: str,
    session_id: str,
    use_replay_table: bool = True,
) -> None:
    if use_replay_table:
        produce_replay_summary(
            team_id=team_id,
            session_id=session_id,
            distinct_id=distinct_id,
            first_timestamp=timestamp,
            last_timestamp=timestamp,
        )


# Pre-compression and events_summary additions which potentially existed for some self-hosted instances
def create_uncompressed_session_recording_event(
    team_id: int,
    distinct_id: str,
    session_id: str,
    window_id: str,
    timestamp: datetime,
    snapshot_data: dict,
) -> str:
    return _insert_session_recording_event(
        team_id=team_id,
        distinct_id=distinct_id,
        session_id=session_id,
        window_id=window_id,
        timestamp=timestamp,
        snapshot_data=snapshot_data,
    )


def create_snapshot(
    session_id: str,
    timestamp: datetime,
    team_id: int,
    distinct_id: Optional[str] = None,
) -> None:
    create_session_recording_events(
        team_id=team_id,
        timestamp=timestamp,
        distinct_id=distinct_id if distinct_id else str(uuid4()),
        session_id=session_id,
    )


def create_snapshots(
    distinct_id: str,
    session_id: str,
    timestamp: datetime,
    team_id: int,
):
    return create_session_recording_events(
        team_id=team_id,
        timestamp=timestamp,
        distinct_id=distinct_id,
        session_id=session_id,
    )
