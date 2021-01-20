from typing import Dict, List, Optional, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_entity_filter
from ee.clickhouse.models.event import ClickhouseEventSerializer
from ee.clickhouse.models.person import get_persons_by_distinct_ids
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.clickhouse_session_recording import filter_sessions_by_recordings
from ee.clickhouse.queries.sessions.clickhouse_sessions import set_default_dates
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.sessions.list import SESSION_SQL
from posthog.models import Entity, Person, Team
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.utils import flatten

Session = Dict
SESSIONS_LIST_DEFAULT_LIMIT = 50


class ClickhouseSessionsList:
    def run(self, filter: SessionsFilter, team: Team, *args, **kwargs) -> Tuple[List[Session], Optional[Dict]]:
        limit = kwargs.get("limit", SESSIONS_LIST_DEFAULT_LIMIT) + 1
        offset = filter.pagination.get("offset", 0)
        filter = set_default_dates(filter)

        filters, params = parse_prop_clauses(filter.person_filter_properties, team.pk)
        filters_select_clause, filters_timestamps_clause, filters_having, action_filter_params = format_action_filters(
            filter
        )

        date_from, date_to, _ = parse_timestamps(filter, team.pk)
        params = {
            **params,
            **action_filter_params,
            "team_id": team.pk,
            "limit": limit,
            "offset": offset,
            "distinct_id_limit": limit + offset,
        }
        query = SESSION_SQL.format(
            date_from=date_from,
            date_to=date_to,
            filters=filters,
            filters_select_clause=filters_select_clause,
            filters_timestamps_clause=filters_timestamps_clause,
            filters_having=filters_having,
            sessions_limit="LIMIT %(offset)s, %(limit)s",
        )
        query_result = sync_execute(query, params)
        result = self._parse_list_results(query_result)

        pagination = None
        if len(result) == limit:
            result.pop()
            pagination = {"offset": offset + limit - 1}

        self._add_person_properties(team, result)

        return filter_sessions_by_recordings(team, result, filter), pagination

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
                session["email"] = distinct_to_person[session["distinct_id"]].properties.get("email")

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
                    "matching_events": list(sorted(set(flatten(result[10:])))),
                }
            )

        return final


def format_action_filters(filter: SessionsFilter) -> Tuple[str, str, str, Dict]:
    if len(filter.action_filters) == 0:
        return "", "", "", {}

    timestamps_clause = select_clause = ""
    having_clause = []
    params: Dict = {}

    for index, entity in enumerate(filter.action_filters):
        timestamp, filter_params = format_action_filter_aggregate(entity, prepend=f"event_matcher_{index}")

        timestamps_clause += f", {timestamp} as event_match_{index}"
        select_clause += f", groupArray(event_match_{index}) as event_match_{index}"
        having_clause.append(f"notEmpty(event_match_{index})")

        params = {**params, **filter_params}

    return select_clause, timestamps_clause, f"HAVING {' AND '.join(having_clause)}", params


def format_action_filter_aggregate(entity: Entity, prepend: str):
    filter_sql, params = format_entity_filter(entity, prepend=prepend)
    if entity.properties:
        filters, filter_params = parse_prop_clauses(entity.properties, prepend=prepend, team_id=None)
        filter_sql += f" {filters}"
        params = {**params, **filter_params}

    return f"({filter_sql}) ? uuid : NULL", params
