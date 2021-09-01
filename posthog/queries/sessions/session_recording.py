import datetime
from typing import (
    Any,
    Callable,
    Dict,
    Generator,
    List,
    Optional,
    Set,
    Tuple,
)

from django.db import connection

from posthog.helpers.session_recording import decompress_chunked_snapshot_data
from posthog.models import Person, SessionRecordingEvent, Team
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.models.session_recording_event import SessionRecordingViewed
from posthog.models.utils import namedtuplefetchall

DistinctId = str
Snapshots = List[Any]


OPERATORS = {"gt": ">", "lt": "<"}
SESSIONS_IN_RANGE_QUERY = """
    SELECT
        session_id,
        distinct_id,
        start_time,
        end_time,
        end_time - start_time as duration
    FROM (
        SELECT
            session_id,
            distinct_id,
            MIN(timestamp) as start_time,
            MAX(timestamp) as end_time,
            MAX(timestamp) - MIN(timestamp) as duration,
            COUNT(*) FILTER(where snapshot_data->>'type' = '2' OR (snapshot_data->>'has_full_snapshot')::boolean) as full_snapshots
        FROM posthog_sessionrecordingevent
        WHERE
            team_id = %(team_id)s
            AND timestamp >= %(start_time)s
            AND timestamp <= %(end_time)s
        GROUP BY distinct_id, session_id
    ) AS p
    WHERE full_snapshots > 0 {filter_query}
"""


class SessionRecording:
    def query_recording_snapshots(
        self, team: Team, session_id: str
    ) -> Tuple[Optional[DistinctId], Optional[datetime.datetime], Snapshots]:
        events = SessionRecordingEvent.objects.filter(team=team, session_id=session_id).order_by("timestamp")

        if len(events) == 0:
            return None, None, []

        return events[0].distinct_id, events[0].timestamp, [e.snapshot_data for e in events]

    def run(self, team: Team, session_recording_id: str, *args, **kwargs) -> Dict[str, Any]:
        from posthog.api.person import PersonSerializer

        distinct_id, start_time, snapshots = self.query_recording_snapshots(team, session_recording_id)
        snapshots = list(decompress_chunked_snapshot_data(team.pk, session_recording_id, snapshots))

        person = (
            PersonSerializer(Person.objects.get(team=team, persondistinctid__distinct_id=distinct_id)).data
            if distinct_id
            else None
        )

        return {
            "snapshots": snapshots,
            "person": person,
            "start_time": start_time,
        }


def query_sessions_in_range(
    team: Team, start_time: datetime.datetime, end_time: datetime.datetime, filter: SessionsFilter
) -> List[dict]:
    filter_query, filter_params = "", {}

    if filter.recording_duration_filter:
        filter_query = f"AND duration {OPERATORS[filter.recording_duration_filter.operator]} INTERVAL '%(min_recording_duration)s seconds'"
        filter_params = {
            "min_recording_duration": filter.recording_duration_filter.value,
        }

    with connection.cursor() as cursor:
        cursor.execute(
            SESSIONS_IN_RANGE_QUERY.format(filter_query=filter_query),
            {"team_id": team.id, "start_time": start_time, "end_time": end_time, **filter_params,},
        )

        results = namedtuplefetchall(cursor)

    return [row._asdict() for row in results]


# :TRICKY: This mutates sessions list
def join_with_session_recordings(
    team: Team, sessions_results: List[Any], filter: SessionsFilter, query: Callable = query_sessions_in_range
) -> List[Any]:
    if len(sessions_results) == 0:
        return sessions_results

    min_ts = min(it["start_time"] for it in sessions_results)
    max_ts = max(it["end_time"] for it in sessions_results)

    session_recordings = query(team, min_ts, max_ts, filter)
    viewed_session_recordings = set(
        SessionRecordingViewed.objects.filter(team=team, user_id=filter.user_id).values_list("session_id", flat=True)
    )

    for session in sessions_results:
        session["session_recordings"] = list(
            collect_matching_recordings(session, session_recordings, filter, viewed_session_recordings)
        )

    if filter.limit_by_recordings:
        sessions_results = [session for session in sessions_results if len(session["session_recordings"]) > 0]
    return sessions_results


def collect_matching_recordings(
    session: Any, session_recordings: List[Any], filter: SessionsFilter, viewed: Set[str]
) -> Generator[Dict, None, None]:
    for recording in session_recordings:
        if matches(session, recording, filter, viewed):
            if isinstance(recording["duration"], datetime.timedelta):
                # postgres
                recording_duration = recording["duration"].total_seconds()
            else:
                # clickhouse
                recording_duration = recording["duration"]
            yield {
                "id": recording["session_id"],
                "recording_duration": recording_duration or 0,
                "viewed": recording["session_id"] in viewed,
                "start_time": recording["start_time"],
                "end_time": recording["end_time"],
            }


def matches(session: Any, session_recording: Any, filter: SessionsFilter, viewed: Set[str]) -> bool:
    return (
        session["distinct_id"] == session_recording["distinct_id"]
        and session["start_time"] <= session_recording["end_time"]
        and session["end_time"] >= session_recording["start_time"]
        and (not filter.recording_unseen_filter or session_recording["session_id"] not in viewed)
    )
