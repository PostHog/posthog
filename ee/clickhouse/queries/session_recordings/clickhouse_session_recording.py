import json
from typing import Any, List

from ee.clickhouse.client import sync_execute
from posthog.models import SessionRecordingEvent
from posthog.queries.session_recordings.session_recording import SessionRecordingMetaData, SessionRecordingSnapshots

DistinctId = str
Snapshots = List[Any]


class ClickhouseSessionRecordingSnapshots(SessionRecordingSnapshots):
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


class ClickhouseSessionRecordingMetaData(SessionRecordingMetaData):

    _recording_metadata_query = """
            SELECT
                count(*) as event_count,
                any(distinct_id) as distinct_id,
                MIN(timestamp) AS start_time,
                MAX(timestamp) AS end_time,
                dateDiff('second', toDateTime(MIN(timestamp)), toDateTime(MAX(timestamp))) as duration
            FROM session_recording_events
            WHERE
                team_id = %(team_id)s
                AND session_id = %(session_recording_id)s
    """

    def run(self, *args, **kwargs):
        query_results = sync_execute(
            self._recording_metadata_query,
            {"team_id": self._team.pk, "session_recording_id": self._session_recording_id},
        )

        return {
            "event_count": query_results[0][0],
            "distinct_id": query_results[0][1],
            "start_time": query_results[0][2],
            "end_time": query_results[0][3],
            "duration": query_results[0][4],
        }
