import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from uuid import uuid4

import structlog

from posthog.client import sync_execute
from posthog.session_recordings.session_recording_helpers import RRWEB_MAP_EVENT_TYPE, compress_and_chunk_snapshots
from posthog.kafka_client.client import ClickhouseProducer
from posthog.kafka_client.topics import KAFKA_SESSION_RECORDING_EVENTS
from posthog.models.session_recording_event.sql import INSERT_SESSION_RECORDING_EVENT_SQL
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
        p.produce(sql=INSERT_SESSION_RECORDING_EVENT_SQL(), topic=KAFKA_SESSION_RECORDING_EVENTS, data=data)
    elif len(snapshot_data_json) <= MAX_INSERT_LENGTH:
        sync_execute(INSERT_SESSION_RECORDING_EVENT_SQL(), data, settings={"max_query_size": MAX_INSERT_LENGTH})

    return str(uuid)


def create_session_recording_events(
    team_id: int,
    timestamp: datetime,
    distinct_id: str,
    session_id: str,
    window_id: Optional[str] = None,
    # If not given we will create a mock full snapshot
    snapshots: Optional[List[dict]] = None,
    chunk_size: Optional[int] = 512 * 1024,
) -> List[str]:

    if window_id is None:
        window_id = session_id

    if not snapshots:
        snapshots = [
            {
                "type": RRWEB_MAP_EVENT_TYPE.FullSnapshot,
                "data": {},
                "timestamp": round(timestamp.timestamp() * 1000),  # NOTE: rrweb timestamps are milliseconds
            }
        ]

    # We use the same code path for chunking events by mocking this as an typical posthog event
    mock_events = [
        {
            "event": "$snapshot",
            "properties": {
                "$session_id": session_id,
                "$window_id": window_id,
                "$snapshot_data": snapshot,
            },
        }
        for snapshot in snapshots
    ]

    event_ids = []

    for event in compress_and_chunk_snapshots(mock_events, chunk_size=chunk_size):
        event_ids.append(
            _insert_session_recording_event(
                team_id=team_id,
                distinct_id=distinct_id,
                session_id=session_id,
                window_id=window_id,
                timestamp=timestamp,
                snapshot_data=event["properties"]["$snapshot_data"],
            )
        )

    return event_ids


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
    window_id: str = "",
    has_full_snapshot: bool = True,
    type: Optional[int] = None,
    data: Optional[Dict] = None,
) -> List[str]:
    if not data:
        data = {"source": 0}

    snapshot_data = {
        "data": {**data},
        "timestamp": round(timestamp.timestamp() * 1000),  # NOTE: rrweb timestamps are milliseconds
        "type": type
        or (RRWEB_MAP_EVENT_TYPE.FullSnapshot if has_full_snapshot else RRWEB_MAP_EVENT_TYPE.IncrementalSnapshot),
    }

    return create_session_recording_events(
        team_id=team_id,
        timestamp=timestamp,
        distinct_id=distinct_id if distinct_id else str(uuid4()),
        session_id=session_id,
        window_id=window_id,
        snapshots=[snapshot_data],
    )


def create_chunked_snapshots(
    snapshot_count: int,
    distinct_id: str,
    session_id: str,
    timestamp: datetime,
    team_id: int,
    window_id: str = "",
    has_full_snapshot: bool = True,
    source: int = 0,
):
    snapshots = []
    for index in range(snapshot_count):
        snapshots.append(
            {
                "type": 2 if has_full_snapshot else 3,
                "data": {
                    "source": source,
                    "texts": [],
                    "attributes": [],
                    "removes": [],
                    "adds": [
                        {
                            "parentId": 4,
                            "nextId": 386,
                            "node": {
                                "type": 2,
                                "tagName": "style",
                                "attributes": {"data-emotion": "css"},
                                "childNodes": [],
                                "id": 729,
                            },
                        }
                    ],
                },
                "timestamp": (timestamp + timedelta(seconds=index)).timestamp() * 1000,
            },
        )

    return create_session_recording_events(
        team_id=team_id,
        timestamp=timestamp,
        distinct_id=distinct_id,
        session_id=session_id,
        window_id=window_id,
        snapshots=snapshots,
        chunk_size=15,
    )
