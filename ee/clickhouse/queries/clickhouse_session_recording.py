import datetime
import json
from typing import Any, Callable, List, Optional, Tuple

from ee.clickhouse.client import sync_execute
from posthog.models import Team
from posthog.queries.base import BaseQuery
from posthog.queries.session_recording import DistinctId
from posthog.queries.session_recording import SessionRecording as BaseSessionRecording
from posthog.queries.session_recording import Snapshots
from posthog.queries.session_recording import add_session_recording_ids as _add_session_recording_ids

SINGLE_RECORDING_QUERY = """
    SELECT distinct_id, snapshot_data
    FROM session_recording_events
    WHERE
        team_id = %(team_id)s
        AND session_id = %(session_id)s
"""

SESSIONS_RECORING_LIST_QUERY = """
    SELECT
        session_id,
        distinct_id,
        MIN(timestamp) AS start_time,
        MAX(timestamp) AS end_time
    FROM session_recording_events
    WHERE
        team_id = %(team_id)s
        AND timestamp >= %(start_time)s
        AND timestamp <= %(end_time)s
        AND JSONExtractInt(snapshot_data, 'type') = 2
    GROUP BY distinct_id, session_id
"""
SESSIONS_RECORING_LIST_QUERY_COLUMNS = ["session_id", "distinct_id", "start_time", "end_time"]


class SessionRecording(BaseSessionRecording):
    def query_recording_snapshots(self, team: Team, session_id: str) -> Tuple[Optional[DistinctId], Snapshots]:
        response = sync_execute(SINGLE_RECORDING_QUERY, {"team_id": team.id, "session_id": session_id})
        if len(response) == 0:
            return None, []
        return response[0][0], [json.loads(snapshot_data) for _, snapshot_data in response]


def add_session_recording_ids(team: Team, sessions_results: List[Any]) -> List[Any]:
    return _add_session_recording_ids(team, sessions_results, query=query_sessions_in_range)


def query_sessions_in_range(team: Team, start_time: datetime.datetime, end_time: datetime.datetime) -> List[dict]:
    results = sync_execute(
        SESSIONS_RECORING_LIST_QUERY,
        {
            "team_id": team.id,
            "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
        },
    )

    return [dict(zip(SESSIONS_RECORING_LIST_QUERY_COLUMNS, row)) for row in results]
