import datetime
from datetime import timedelta
from typing import Dict, Optional
from uuid import uuid4

from posthog.helpers.session_recording import compress_and_chunk_snapshots
from posthog.models.session_recording_event.util import create_session_recording_event


def _create_session_recording_event(**kwargs) -> str:
    return create_session_recording_event(uuid=uuid4(), **kwargs,)


def create_snapshot(
    session_id: str,
    timestamp: datetime.datetime,
    team_id: int,
    distinct_id: Optional[str] = None,
    window_id: str = "",
    has_full_snapshot: bool = True,
    type: int = 2,
    data: Optional[Dict] = None,
) -> str:
    if not data:
        data = {"source": 0}

    snapshot_data = {
        "data": {**data},
        "timestamp": timestamp.timestamp() * 1000,
        "has_full_snapshot": has_full_snapshot,
        "type": type,
    }

    return _create_session_recording_event(
        team_id=team_id,
        distinct_id=distinct_id if distinct_id else uuid4(),
        timestamp=timestamp,
        session_id=session_id,
        window_id=window_id,
        snapshot_data=snapshot_data,
    )


def create_chunked_snapshots(
    snapshot_count: int,
    distinct_id: str,
    session_id: str,
    timestamp: datetime.datetime,
    team_id: int,
    window_id: str = "",
    has_full_snapshot: bool = True,
    source: int = 0,
):
    snapshot = []
    for index in range(snapshot_count):
        snapshot.append(
            {
                "event": "$snapshot",
                "properties": {
                    "$snapshot_data": {
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
                                },
                            ],
                        },
                        "timestamp": (timestamp + timedelta(seconds=index)).timestamp() * 1000,
                    },
                    "$window_id": window_id,
                    "$session_id": session_id,
                    "distinct_id": distinct_id,
                },
            }
        )
    chunked_snapshots = compress_and_chunk_snapshots(
        snapshot, chunk_size=15
    )  # Small chunk size makes sure the snapshots are chunked for the test
    for snapshot_chunk in chunked_snapshots:
        _create_session_recording_event(
            team_id=team_id,
            distinct_id=distinct_id,
            timestamp=timestamp,
            session_id=session_id,
            window_id=window_id,
            snapshot_data=snapshot_chunk["properties"].get("$snapshot_data"),
        )
