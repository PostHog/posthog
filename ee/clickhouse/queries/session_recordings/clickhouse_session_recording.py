import json
from typing import Dict, List

from posthog.client import sync_execute
from posthog.models import SessionRecordingEvent
from posthog.queries.session_recordings.session_recording import SessionRecording
from posthog.storage import object_storage


def read_from_object_storage(session_id: str, snapshot_data: Dict) -> Dict:
    file_content = object_storage.read(
        f"{session_id}/{snapshot_data.get('chunk_id', 'unknown')}/{snapshot_data.get('chunk_index', 'unknown')}"
    )
    snapshot_data["data"] = file_content
    return snapshot_data


class ClickhouseSessionRecording(SessionRecording):
    _recording_snapshot_query = """
        SELECT session_id, window_id, distinct_id, timestamp, snapshot_data
        FROM session_recording_events
        WHERE
            team_id = %(team_id)s
            AND session_id = %(session_id)s
        ORDER BY timestamp
    """

    def _query_recording_snapshots(self) -> List[SessionRecordingEvent]:
        response = sync_execute(
            self._recording_snapshot_query, {"team_id": self._team.id, "session_id": self._session_recording_id,},
        )

        events = []

        for (session_id, window_id, distinct_id, timestamp, snapshot_data) in response:

            snapshot_data = json.loads(snapshot_data)
            has_payload_chunk = snapshot_data.get("Data", None) is not None
            loaded_data = snapshot_data if has_payload_chunk else read_from_object_storage(session_id, snapshot_data)

            events.append(
                SessionRecordingEvent(
                    session_id=session_id,
                    window_id=window_id,
                    distinct_id=distinct_id,
                    timestamp=timestamp,
                    snapshot_data=loaded_data,
                )
            )

        return events
