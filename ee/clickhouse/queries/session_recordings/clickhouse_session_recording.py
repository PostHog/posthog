import json
from typing import List

from ee.clickhouse.client import sync_execute
from posthog.models import SessionRecordingEvent
from posthog.queries.session_recordings.session_recording import SessionRecording


class ClickhouseSessionRecording(SessionRecording):
    _recording_snapshot_query = """
        SELECT distinct_id, timestamp, snapshot_data
        FROM session_recording_events
        WHERE
            team_id = %(team_id)s
            AND session_id = %(session_id)s
        ORDER BY timestamp
    """

    def query_recording_snapshots(self) -> List[SessionRecordingEvent]:
        response = sync_execute(
            self._recording_snapshot_query, {"team_id": self._team.id, "session_id": self._session_recording_id,},
        )
        return [
            SessionRecordingEvent(distinct_id=distinct_id, timestamp=timestamp, snapshot_data=json.loads(snapshot_data))
            for distinct_id, timestamp, snapshot_data in response
        ]
