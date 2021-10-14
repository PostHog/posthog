import datetime
import json
from typing import Any, List, Optional, Tuple

from ee.clickhouse.client import sync_execute
from posthog.queries.session_recordings.session_recording import SessionRecording

DistinctId = str
Snapshots = List[Any]

SINGLE_RECORDING_QUERY = """
    SELECT distinct_id, timestamp, snapshot_data
    FROM session_recording_events
    WHERE
        team_id = %(team_id)s
        AND session_id = %(session_id)s
    ORDER BY timestamp
"""


class ClickhouseSessionRecording(SessionRecording):
    def query_recording_snapshots(self) -> Tuple[Optional[DistinctId], Optional[datetime.datetime], Snapshots]:
        response = sync_execute(
            SINGLE_RECORDING_QUERY, {"team_id": self._team.id, "session_id": self._session_recording_id}
        )
        if len(response) == 0:
            return None, None, []
        return response[0][0], response[0][1], [json.loads(snapshot_data) for _, _, snapshot_data in response]
