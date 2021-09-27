import datetime
import json
from typing import Any, Dict, List, Optional, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.queries.util import get_earliest_timestamp
from ee.clickhouse.sql.person import GET_TEAM_PERSON_DISTINCT_IDS
from posthog.models import Filter, SessionRecordingViewed, Team
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
SESSIONS_FOR_FUNNEL_PERSONS_QUERY = f"""
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
    HAVING full_snapshots > 0"""


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


def join_funnel_persons_with_session_recordings(
    persons_serialized: List[dict], filter: Filter, team: Team, requesting_user_id: int
) -> List[dict]:
    persons_uuid_map: Dict[str, Dict[str, Any]] = {}
    all_distinct_ids: List[str] = []
    for person in persons_serialized:
        persons_uuid_map[str(person["uuid"])] = person
        all_distinct_ids.extend(person["distinct_ids"])

    window_timedelta = datetime.timedelta(
        **{f"{filter.funnel_window_interval_unit_or_default}s": filter.funnel_window_interval_or_default}
    )
    session_recordings = query_sessions_for_funnel_persons(
        team,
        # We are sure that date_from and date_to have values here, as they're ensured in the superclass
        filter.date_from or get_earliest_timestamp(team.id),
        filter.date_to + window_timedelta,
        all_distinct_ids,
    )
    if session_recordings:
        viewed_session_recordings = set(
            SessionRecordingViewed.objects.filter(team=team, user_id=requesting_user_id).values_list(
                "session_id", flat=True
            )
        )
        for recording in session_recordings:
            row = {
                "id": recording["session_id"],
                "recording_duration": recording["duration"],
                "viewed": recording["session_id"] in viewed_session_recordings,
                "start_time": recording["start_time"].isoformat(),
                "end_time": recording["end_time"].isoformat(),
                "person_id": str(recording["person_id"]),
            }
            person_uuid = row["person_id"]
            if not "session_recordings" in persons_uuid_map[person_uuid]:
                persons_uuid_map[person_uuid]["session_recordings"] = []
            persons_uuid_map[person_uuid]["session_recordings"].append(row)
    return persons_serialized
