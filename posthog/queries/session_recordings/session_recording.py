import dataclasses
import json
from typing import Dict, List, Optional, cast

from rest_framework.request import Request

from posthog.client import sync_execute
from posthog.helpers.session_recording import (
    DecompressedRecordingData,
    RecordingSegment,
    SnapshotDataTaggedWithWindowId,
    WindowId,
    decompress_chunked_snapshot_data,
    get_event_summaries_from_compressed_snapshot_data,
    get_metadata_from_event_summaries,
)
from posthog.models import SessionRecordingEvent, Team


@dataclasses.dataclass
class RecordingMetadata:
    distinct_id: str
    segments: List[RecordingSegment]
    start_and_end_times_by_window_id: Dict[WindowId, Dict]


class SessionRecording:
    _request: Request
    _session_recording_id: str
    _team: Team

    def __init__(self, request: Request, session_recording_id: str, team: Team) -> None:
        self._request = request
        self._session_recording_id = session_recording_id
        self._team = team

    _recording_snapshot_query = """
        SELECT session_id, window_id, distinct_id, timestamp, snapshot_data
        FROM session_recording_events
        PREWHERE
            team_id = %(team_id)s
            AND session_id = %(session_id)s
        ORDER BY timestamp
    """

    def _query_recording_snapshots(self) -> List[SessionRecordingEvent]:
        response = sync_execute(
            self._recording_snapshot_query, {"team_id": self._team.id, "session_id": self._session_recording_id,},
        )
        return [
            SessionRecordingEvent(
                session_id=session_id,
                window_id=window_id,
                distinct_id=distinct_id,
                timestamp=timestamp,
                snapshot_data=json.loads(snapshot_data),
            )
            for session_id, window_id, distinct_id, timestamp, snapshot_data in response
        ]

    def get_snapshots(self, limit, offset) -> DecompressedRecordingData:
        all_snapshots = [
            SnapshotDataTaggedWithWindowId(
                window_id=recording_snapshot.window_id, snapshot_data=recording_snapshot.snapshot_data
            )
            for recording_snapshot in self._query_recording_snapshots()
        ]
        return decompress_chunked_snapshot_data(self._team.pk, self._session_recording_id, all_snapshots, limit, offset)

    def get_metadata(self) -> Optional[RecordingMetadata]:
        all_snapshots: List[SnapshotDataTaggedWithWindowId] = []

        distinct_id = None
        for index, session_recording_event in enumerate(self._query_recording_snapshots()):
            if index == 0:
                distinct_id = session_recording_event.distinct_id
            all_snapshots.append(
                SnapshotDataTaggedWithWindowId(
                    window_id=session_recording_event.window_id, snapshot_data=session_recording_event.snapshot_data
                )
            )

        if len(all_snapshots) == 0:
            return None

        event_summaries = get_event_summaries_from_compressed_snapshot_data(
            self._team.pk, self._session_recording_id, all_snapshots
        )

        segments, start_and_end_times_by_window_id = get_metadata_from_event_summaries(event_summaries)

        return RecordingMetadata(
            segments=segments,
            start_and_end_times_by_window_id=start_and_end_times_by_window_id,
            distinct_id=cast(str, distinct_id),
        )
