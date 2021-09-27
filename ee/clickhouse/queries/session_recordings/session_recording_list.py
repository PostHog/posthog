from typing import Any, Dict, List

from ee.clickhouse.client import sync_execute
from posthog.queries.session_recordings.session_recording_list import SessionRecordingList


class ClickhouseSessionRecordingList(SessionRecordingList):
    _query: str = """
    SELECT
        session_id,
        distinct_id,
        start_time,
        end_time,
        dateDiff('second', toDateTime(start_time), toDateTime(end_time)) as duration
    FROM (
        SELECT
            session_id,
            distinct_id,
            MIN(timestamp) AS start_time,
            MAX(timestamp) AS end_time,
            COUNT((JSONExtractInt(snapshot_data, 'type') = 2 OR JSONExtractBool(snapshot_data, 'has_full_snapshot')) ? 1 : NULL) as full_snapshots
        FROM session_recording_events
        WHERE
                team_id = {team_id}
                {distinct_id_clause}
        GROUP BY distinct_id, session_id
        ORDER BY start_time DESC
    )
    WHERE full_snapshots > 0
    LIMIT {limit}
    """

    def data_to_return(self, results: List[Any]) -> List[Dict[str, Any]]:
        return [dict(zip(["session_id", "distinct_id", "start_time", "end_time", "duration"], row)) for row in results]

    def run(self, *args, **kwargs) -> List[Dict[str, Any]]:
        query, query_params = self._build_query()
        results = sync_execute(query, query_params)
        return self.data_to_return(results)
