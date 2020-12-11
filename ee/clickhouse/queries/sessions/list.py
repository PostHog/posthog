from typing import Any, Dict, List, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.event import ClickhouseEventSerializer
from ee.clickhouse.models.person import get_persons_by_distinct_ids
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.clickhouse_session_recording import filter_sessions_by_recordings
from ee.clickhouse.queries.sessions.clickhouse_sessions import set_default_dates
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.sessions.list import SESSION_SQL
from posthog.models import Person, Team
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.queries.base import BaseQuery

SESSIONS_LIST_DEFAULT_LIMIT = 50


class ClickhouseSessionsList(BaseQuery):
    def run(self, filter: SessionsFilter, team: Team, *args, **kwargs) -> List[Dict[str, Any]]:
        limit = kwargs.get("limit", SESSIONS_LIST_DEFAULT_LIMIT)
        offset = kwargs.get("offset", 0)
        set_default_dates(filter)

        filters, params = parse_prop_clauses(filter.properties, team.pk)

        date_from, date_to, _ = parse_timestamps(filter, team.pk)
        params = {**params, "team_id": team.pk, "limit": limit, "offset": offset, "distinct_id_limit": limit + offset}
        query = SESSION_SQL.format(
            date_from=date_from, date_to=date_to, filters=filters, sessions_limit="LIMIT %(offset)s, %(limit)s",
        )
        query_result = sync_execute(query, params)
        result = self._parse_list_results(query_result)

        self._add_person_properties(team, result)

        return filter_sessions_by_recordings(team, result, filter)

    def _add_person_properties(self, team=Team, sessions=List[Tuple]):
        distinct_id_hash = {}
        for session in sessions:
            distinct_id_hash[session["distinct_id"]] = True
        distinct_ids = list(distinct_id_hash.keys())

        if len(distinct_ids) == 0:
            return

        persons = get_persons_by_distinct_ids(team.pk, distinct_ids)

        distinct_to_person: Dict[str, Person] = {}
        for person in persons:
            for distinct_id in person.distinct_ids:
                distinct_to_person[distinct_id] = person

        for session in sessions:
            if distinct_to_person.get(session["distinct_id"], None):
                session["properties"] = distinct_to_person[session["distinct_id"]].properties

    def _parse_list_results(self, results: List[Tuple]):
        final = []
        for result in results:
            events = []
            for i in range(len(result[4])):
                event = [
                    result[4][i],  # uuid
                    result[5][i],  # event
                    result[6][i],  # properties
                    result[7][i],  # timestamp
                    None,  # team_id,
                    result[0],  # distinct_id
                    result[8][i],  # elements_chain
                    None,  # properties keys
                    None,  # properties values
                ]
                events.append(ClickhouseEventSerializer(event, many=False).data)

            final.append(
                {
                    "distinct_id": result[0],
                    "global_session_id": result[1],
                    "length": result[2],
                    "start_time": result[3],
                    "end_time": result[9],
                    "event_count": len(result[4]),
                    "events": list(events),
                    "properties": {},
                }
            )

        return final
