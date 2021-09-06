import datetime
import json
from typing import Any, List, Optional, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.sql.person import GET_TEAM_PERSON_DISTINCT_IDS
from posthog.models import Team
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.queries.sessions.session_recording import DistinctId
from posthog.queries.sessions.session_recording import SessionRecording as BaseSessionRecording
from posthog.queries.sessions.session_recording import Snapshots
from posthog.queries.sessions.session_recording import join_with_session_recordings as _join_with_session_recordings

OPERATORS = {"gt": ">", "lt": "<"}

SINGLE_RECORDING_QUERY = """
    SELECT distinct_id, timestamp, snapshot_data
    FROM session_recording_events
    WHERE
        team_id = %(team_id)s
        AND session_id = %(session_id)s
    ORDER BY timestamp
"""

SESSIONS_IN_RANGE_QUERY_COLUMNS = ["session_id", "distinct_id", "start_time", "end_time", "duration", "full_snapshots"]
SESSIONS_IN_RANGE_QUERY = """
    SELECT
        session_id,
        distinct_id,
        MIN(timestamp) AS start_time,
        MAX(timestamp) AS end_time,
        dateDiff('second', toDateTime(start_time), toDateTime(end_time)) AS duration,
        countIf(JSONExtractInt(snapshot_data, 'type') = 2 OR JSONExtractBool(snapshot_data, 'has_full_snapshot')) AS full_snapshots
    FROM session_recording_events
    WHERE
        team_id = %(team_id)s
        AND timestamp >= %(start_time)s
        AND timestamp <= %(end_time)s
    GROUP BY distinct_id, session_id
    HAVING full_snapshots > 0
    {filter_query}"""

SESSIONS_FOR_FUNNEL_PERSONS_QUERY_COLUMNS = [
    "session_id",
    "person_id",
    "start_time",
    "end_time",
    "duration",
    "full_snapshots",
]
SESSIONS_FOR_FUNNEL_PERSONS_QUERY = """
    SELECT
        session_id,
        person_id,
        MIN(timestamp) AS start_time,
        MAX(timestamp) AS end_time,
        dateDiff('second', toDateTime(start_time), toDateTime(end_time)) AS duration,
        countIf(JSONExtractInt(snapshot_data, 'type') = 2 OR JSONExtractBool(snapshot_data, 'has_full_snapshot')) AS full_snapshots
    FROM session_recording_events
    INNER JOIN (
        {GET_TEAM_PERSON_DISTINCT_IDS}
    ) pdi
    USING distinct_id
    WHERE
        team_id = %(team_id)s
        AND timestamp >= %(start_time)s
        AND timestamp <= %(end_time)s
        AND has(%(distinct_ids)s, distinct_id)
    GROUP BY person_id, session_id
    HAVING full_snapshots > 0""".format(
    GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS
)


class SessionRecording(BaseSessionRecording):
    def query_recording_snapshots(
        self, team: Team, session_id: str
    ) -> Tuple[Optional[DistinctId], Optional[datetime.datetime], Snapshots]:
        response = sync_execute(SINGLE_RECORDING_QUERY, {"team_id": team.id, "session_id": session_id})
        if len(response) == 0:
            return None, None, []
        return response[0][0], response[0][1], [json.loads(snapshot_data) for _, _, snapshot_data in response]


def join_with_session_recordings(team: Team, sessions_results: List[Any], filter: SessionsFilter) -> List[Any]:
    return _join_with_session_recordings(team, sessions_results, filter, query=query_sessions_in_range)


def query_sessions_for_funnel_persons(
    team: Team, start_time: datetime.datetime, end_time: datetime.datetime, distinct_ids: List[DistinctId]
) -> List[dict]:
    results = sync_execute(
        SESSIONS_FOR_FUNNEL_PERSONS_QUERY,
        {
            "team_id": team.id,
            "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "distinct_ids": distinct_ids,
        },
    )

    return [dict(zip(SESSIONS_FOR_FUNNEL_PERSONS_QUERY_COLUMNS, row)) for row in results]


def query_sessions_in_range(
    team: Team, start_time: datetime.datetime, end_time: datetime.datetime, filter: SessionsFilter
) -> List[dict]:
    filter_query, extra_params = "", {}

    if filter.recording_duration_filter:
        filter_query = f"AND duration {OPERATORS[filter.recording_duration_filter.operator]} %(min_recording_duration)s"  # type: ignore
        extra_params["min_recording_duration"] = filter.recording_duration_filter.value

    results = sync_execute(
        SESSIONS_IN_RANGE_QUERY.format(filter_query=filter_query),
        {
            "team_id": team.id,
            "start_time": start_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "end_time": end_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
            **extra_params,
        },
    )

    return [dict(zip(SESSIONS_IN_RANGE_QUERY_COLUMNS, row)) for row in results]
