from datetime import datetime, timedelta
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
from rest_framework.request import Request

from posthog.helpers.session_recording import decompress_chunked_snapshot_data
from posthog.models import Person, SessionRecordingEvent, Team
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.models.session_recording_event import SessionRecordingViewed
from posthog.models.utils import namedtuplefetchall
from posthog.queries.sessions.utils import cached_recording
from posthog.utils import format_query_params_absolute_url, get_milliseconds_between_dates

DistinctId = str
Snapshots = List[Any]
Events = Tuple[str, str, Snapshots]


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

# Arbitrarily large number that acts as an FF for chunked session recording loading
RECORDINGS_NUM_SNAPSHOTS_LIMIT = 1000000000


class SessionRecording:
    _request: Request
    _filter: SessionRecordingsFilter
    _session_recording_id: str
    _team: Team
    _limit: int
    _offset: int

    def __init__(
        self, request: Request, filter: SessionRecordingsFilter, session_recording_id: str, team: Team
    ) -> None:
        self._request = request
        self._filter = filter
        self._session_recording_id = session_recording_id
        self._team = team
        self._limit = self._filter.limit if self._filter.limit else RECORDINGS_NUM_SNAPSHOTS_LIMIT
        self._offset = self._filter.offset if self._filter.offset else 0

    def query_recording_snapshots(self) -> List[SessionRecordingEvent]:
        return SessionRecordingEvent.objects.filter(team=self._team, session_id=self._session_recording_id).order_by(
            "timestamp"
        )

    # @cached_recording TODO: uncomment once it's determined safe to cache session recordings
    def get_snapshot_data(self) -> Tuple[Optional[DistinctId], Optional[datetime], Snapshots]:
        events = self.query_recording_snapshots()

        if len(events) == 0:
            return None, None, []

        return (
            events[0].distinct_id,
            events[0].timestamp,
            list(
                decompress_chunked_snapshot_data(
                    self._team.pk, self._session_recording_id, [e.snapshot_data for e in events]
                )
            ),
        )

    def run(self) -> Dict[str, Any]:
        from posthog.api.person import PersonSerializer

        distinct_id, start_time, snapshots = self.get_snapshot_data()

        # Apply limit and offset after decompressing to account for non-fully formed chunks.
        snapshots_subset = snapshots[self._offset : (self._offset + self._limit)]
        duration = 0
        if len(snapshots) > 1:
            duration = get_milliseconds_between_dates(
                datetime.fromtimestamp(snapshots[-1].get("timestamp", 0) / 1000.0),
                datetime.fromtimestamp(snapshots[0].get("timestamp", 0) / 1000.0),
            )
        has_next = len(snapshots) > (self._offset + self._limit + 1)
        next_url = (
            format_query_params_absolute_url(self._request, self._offset + self._limit, self._limit)
            if has_next
            else None
        )

        person = (
            PersonSerializer(Person.objects.get(team=self._team, persondistinctid__distinct_id=distinct_id)).data
            if distinct_id
            else None
        )

        return {
            "snapshots": snapshots_subset,
            "person": person,
            "start_time": start_time,
            "next": next_url,
            "duration": duration,
        }


def query_sessions_in_range(team: Team, start_time: datetime, end_time: datetime, filter: SessionsFilter) -> List[dict]:
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
            if isinstance(recording["duration"], timedelta):
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
