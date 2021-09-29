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

    _query: str = """
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
            GROUP BY distinct_id, session_id
        ) AS p
        WHERE full_snapshots > 0 
        ORDER BY start_time DESC
        LIMIT %(limit)s
    """

    def _build_query(self) -> Tuple[str, Dict]:
        distinct_id_clause = ""
        params = {"team_id": self._team.pk, "limit": self.SESSION_RECORDINGS_DEFAULT_LIMIT}
        if self._filter.distinct_id:
            distinct_ids = Person.objects.get(
                team=self._team, persondistinctid__distinct_id=self._filter.distinct_id
            ).distinct_ids
            distinct_id_clause = f"AND distinct_id IN %(distinct_ids)s"
            params = {**params, "distinct_ids": distinct_ids}

        return (
            self._query.format(distinct_id_clause=distinct_id_clause,),
            params,
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
