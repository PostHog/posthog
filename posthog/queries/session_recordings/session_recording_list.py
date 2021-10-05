from datetime import timedelta
from typing import Any, Dict, List, Tuple

from django.db import connection

from posthog.models import Person, Team
from posthog.models.filters.session_recordings_filter import SessionRecordingsFilter
from posthog.models.utils import namedtuplefetchall, sane_repr
from posthog.queries.base import BaseQuery


class SessionRecordingList(BaseQuery):
    SESSION_RECORDINGS_DEFAULT_LIMIT = 50
    _filter: SessionRecordingsFilter
    _team: Team

    def __init__(self, filter: SessionRecordingsFilter, team: Team) -> None:
        self._filter = filter
        self._team = team

    _core_session_recording_query: str = """
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
            {distinct_id_clause}
            {timestamp_clause}
        GROUP BY session_id, distinct_id
    """

    _basic_session_recordings_query: str = """
        SELECT
            session_id,
            distinct_id,
            start_time,
            end_time,
            end_time - start_time as duration
        FROM (
            {core_session_recording_query}
        ) AS p
        WHERE full_snapshots > 0
        {duration_clause}
        ORDER BY start_time DESC
        LIMIT %(limit)s OFFSET %(offset)s
    """

    def _has_entity_filters(self):
        return self._filter.entities and len(self._filter.entities) > 0

    # We want to select events beyond the range of the recording to handle the case where
    # a recording spans the time boundaries
    def _get_events_timestamp_clause(self):
        timestamp_clause = ""
        timestamp_params = {}
        if self._filter.date_from:
            timestamp_clause += "\nAND timestamp >= %(event_start_time)s"
            timestamp_params["event_start_time"] = self._filter.date_from - timedelta(hours=12)
        if self._filter.date_to:
            timestamp_clause += "\nAND timestamp <= %(event_end_time)s"
            timestamp_params["event_end_time"] = self._filter.date_to + timedelta(hours=12)
        return timestamp_params, timestamp_clause

    def _get_recording_start_time_clause(self):
        start_time_clause = ""
        start_time_params = {}
        if self._filter.date_from:
            start_time_clause += "\nAND start_time >= %(start_time)s"
            start_time_params["start_time"] = self._filter.date_from
        if self._filter.date_to:
            start_time_clause += "\nAND start_time <= %(end_time)s"
            start_time_params["end_time"] = self._filter.date_to
        return start_time_params, start_time_clause

    def _get_person_id_clause(self):
        person_id_clause = ""
        person_id_params = {}
        if self._filter.person_uuid:
            person_id_clause = f"AND person_distinct_id.person_id = %(person_uuid)s"
            person_id_params = {"person_uuid": self._filter.person_uuid}
        return person_id_params, person_id_clause

    def _get_duration_clause(self):
        duration_clause = ""
        duration_params = {}
        if self._filter.recording_duration_filter:
            if self._filter.recording_duration_filter.operator == "gt":
                operator = ">"
            else:
                operator = "<"

            duration_clause = f"AND duration {operator} INTERVAL '%(recording_duration)s seconds'"
            duration_params = {
                "recording_duration": filter.recording_duration_filter.value,
            }
        return duration_params, duration_clause

    def _build_query(self) -> Tuple[str, Dict]:
        params = {"team_id": self._team.pk, "limit": self.SESSION_RECORDINGS_DEFAULT_LIMIT, "offset": 0}
        timestamp_params, timestamp_clause = self._get_timestamp_clause()
        distinct_id_params, distinct_id_clause = self._get_distinct_id_clause()

        return (
            self._basic_session_recordings_query.format(
                distinct_id_clause=distinct_id_clause, timestamp_clause=timestamp_clause,
            ),
            {**params, **distinct_id_params, **timestamp_params},
        )

    def data_to_return(self, results: List[Any]) -> List[Dict[str, Any]]:
        return [row._asdict() for row in results]

    def run(self, *args, **kwargs) -> List[Dict[str, Any]]:
        with connection.cursor() as cursor:
            query, query_params = self._build_query()
            cursor.execute(query, query_params)
            results = namedtuplefetchall(cursor)
        return self.data_to_return(results)

    __repr__ = sane_repr("_team", "_filter")
