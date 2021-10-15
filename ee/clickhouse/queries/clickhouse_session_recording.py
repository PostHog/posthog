import datetime
import json
from typing import Any, List

from ee.clickhouse.client import sync_execute
from posthog.models import SessionRecordingEvent, Team
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.queries.sessions.session_recording import SessionRecording as BaseSessionRecording
from posthog.queries.sessions.session_recording import join_with_session_recordings as _join_with_session_recordings
from posthog.queries.sessions.utils import cached_recording

OPERATORS = {"gt": ">", "lt": "<"}

SINGLE_RECORDING_QUERY = """
    SELECT distinct_id, timestamp, snapshot_data
    FROM session_recording_events
    WHERE
        team_id = %(team_id)s
        AND session_id = %(session_id)s
    ORDER BY timestamp
"""

SESSIONS_IN_RANGE_QUERY = """
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
            team_id = %(team_id)s
            AND timestamp >= %(start_time)s
            AND timestamp <= %(end_time)s
        GROUP BY distinct_id, session_id
    )
    WHERE full_snapshots > 0 {filter_query}
"""
SESSIONS_IN_RANGE_QUERY_COLUMNS = ["session_id", "distinct_id", "start_time", "end_time", "duration"]


class SessionRecording(BaseSessionRecording):
    def query_recording_snapshots(self) -> List[SessionRecordingEvent]:
        response = sync_execute(
            SINGLE_RECORDING_QUERY, {"team_id": self._team.id, "session_id": self._session_recording_id,},
        )
        return [
            SessionRecordingEvent(distinct_id=distinct_id, timestamp=timestamp, snapshot_data=json.loads(snapshot_data))
            for distinct_id, timestamp, snapshot_data in response
        ]


def join_with_session_recordings(team: Team, sessions_results: List[Any], filter: SessionsFilter) -> List[Any]:
    return _join_with_session_recordings(team, sessions_results, filter, query=query_sessions_in_range)


def query_sessions_in_range(
    team: Team, start_time: datetime.datetime, end_time: datetime.datetime, filter: SessionsFilter
) -> List[dict]:
    filter_query, filter_params = "", {}

    if filter.recording_duration_filter:
        filter_query = f"AND duration {OPERATORS[filter.recording_duration_filter.operator]} %(min_recording_duration)s"  # type: ignore
        filter_params = {
            "min_recording_duration": filter.recording_duration_filter.value,
        }

    results = sync_execute(
        SESSIONS_IN_RANGE_QUERY.format(filter_query=filter_query),
        {
            "team_id": team.id,
            "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
            **filter_params,
        },
    )

    return [dict(zip(SESSIONS_IN_RANGE_QUERY_COLUMNS, row)) for row in results]
