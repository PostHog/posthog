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

    _basic_session_recordings_query: str = """
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
                {distinct_id_clause}
                {timestamp_clause}
            GROUP BY session_id, distinct_id
        ) AS p
        WHERE full_snapshots > 0 
        ORDER BY start_time DESC
    LIMIT %(limit)s OFFSET %(offset)s
    """

    def _has_entity_filters(self):
        return self._filter.entities and len(self._filter.entities) > 0

    def _get_timestamp_clause(self):
        timestamp_clause = ""
        timestamp_params = {}
        if self._filter.date_from:
            timestamp_clause += "\nAND timestamp >= %(start_time)s"
            timestamp_params["start_time"] = self._filter.date_from
        if self._filter.date_to:
            timestamp_clause += "\nAND timestamp <= %(end_time)s"
            timestamp_params["end_time"] = self._filter.date_to
        return timestamp_params, timestamp_clause

    def _get_distinct_id_clause(self):
        distinct_id_clause = ""
        distinct_id_params = {}
        if self._filter.distinct_id:
            distinct_ids = Person.objects.get(
                team=self._team, persondistinctid__distinct_id=self._filter.distinct_id
            ).distinct_ids
            distinct_id_clause = f"AND distinct_id IN %(distinct_ids)s"
            distinct_id_params = {"distinct_ids": distinct_ids}
        return distinct_id_params, distinct_id_clause

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
