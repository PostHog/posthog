import datetime
import json
from typing import Any, Callable, List, Optional, Tuple

from ee.clickhouse.client import sync_execute
from posthog.models import Team
from posthog.models.filters.sessions_filter import SessionsFilter
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
        start_time,
        end_time,
        dateDiff('second', toDateTime(start_time), toDateTime(end_time)) as duration
    FROM (
        SELECT
            session_id,
            distinct_id,
            MIN(timestamp) AS start_time,
            MAX(timestamp) AS end_time,
            COUNT(JSONExtractInt(snapshot_data, 'type') = 2 ? 1 : NULL) as full_snapshots
        FROM session_recording_events
        WHERE
            team_id = %(team_id)s
            AND timestamp >= %(start_time)s
            AND timestamp <= %(end_time)s
        GROUP BY distinct_id, session_id
    )
    WHERE full_snapshots > 0 {filter_query}
"""
SESSIONS_RECORING_LIST_QUERY_COLUMNS = ["session_id", "distinct_id", "start_time", "end_time", "duration"]


class SessionRecording(BaseSessionRecording):
    def query_recording_snapshots(self, team: Team, session_id: str) -> Tuple[Optional[DistinctId], Snapshots]:
        response = sync_execute(SINGLE_RECORDING_QUERY, {"team_id": team.id, "session_id": session_id})
        if len(response) == 0:
            return None, []
        return response[0][0], [json.loads(snapshot_data) for _, snapshot_data in response]


def add_session_recording_ids(team: Team, sessions_results: List[Any]) -> List[Any]:
    return _add_session_recording_ids(team, sessions_results, query=query_sessions_in_range)


def filter_sessions_by_recordings(team: Team, sessions_results: List[Any], filter: SessionsFilter) -> List[Any]:
    if len(sessions_results) == 0:
        return sessions_results

    print([filter])

    min_ts = min(it["start_time"] for it in sessions_results)
    max_ts = max(it["end_time"] for it in sessions_results)

    session_recordings = query_sessions_in_range(team, min_ts, max_ts, filter)

    for session in sessions_results:
        session["session_recording_ids"] = [
            recording["session_id"] for recording in session_recordings if matches(session, recording)
        ]

    if filter.limit_by_recordings:
        sessions_results = [session for session in sessions_results if len(session["session_recording_ids"]) > 0]
    return sessions_results


def query_sessions_in_range(
    team: Team, start_time: datetime.datetime, end_time: datetime.datetime, filter: SessionsFilter
) -> List[dict]:
    filter_query, filter_params = "", {}

    if filter.min_recording_duration:
        filter_query = "AND duration >= %(min_recording_duration)s"
        filter_params = {
            "min_recording_duration": filter.min_recording_duration,
        }

    results = sync_execute(
        SESSIONS_RECORING_LIST_QUERY.format(filter_query=filter_query),
        {
            "team_id": team.id,
            "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
            **filter_params,
        },
    )

    return [dict(zip(SESSIONS_RECORING_LIST_QUERY_COLUMNS, row)) for row in results]


def matches(session: Any, session_recording: Any) -> bool:
    return (
        session["distinct_id"] == session_recording["distinct_id"]
        and session["start_time"] <= session_recording["end_time"]
        and session["end_time"] >= session_recording["start_time"]
    )
