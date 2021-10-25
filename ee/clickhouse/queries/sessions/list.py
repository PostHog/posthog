from collections import namedtuple
from typing import Any, Dict, List, Optional, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_entity_filter
from ee.clickhouse.models.event import ClickhouseEventSerializer
from ee.clickhouse.models.person import get_persons_by_distinct_ids
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.clickhouse_session_recording import join_with_session_recordings
from ee.clickhouse.queries.sessions.clickhouse_sessions import set_default_dates
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.sessions.list import SESSION_SQL, SESSIONS_DISTINCT_ID_SQL
from posthog.models import Entity, Person
from posthog.models.filters.sessions_filter import SessionsFilter
from posthog.queries.sessions.sessions_list import SessionsList
from posthog.utils import flatten

Session = Dict
ActionFiltersSQL = namedtuple(
    "ActionFiltersSQL", ["select_clause", "matches_action_clauses", "filters_having", "matches_any_clause", "params"]
)


class ClickhouseSessionsList(SessionsList):
    def fetch_page(self) -> Tuple[List[Session], Optional[Dict]]:
        limit = self.limit + 1
        self.filter = set_default_dates(self.filter)  # type: ignore
        offset = self.filter.pagination.get("offset", 0)
        distinct_id_offset = self.filter.pagination.get("distinct_id_offset", 0)

        action_filters = format_action_filters(self.filter)

        date_from, date_to, date_params = parse_timestamps(self.filter, self.team.pk)
        distinct_ids = self.fetch_distinct_ids(
            action_filters, date_from, date_to, date_params, limit, distinct_id_offset
        )

        query = SESSION_SQL.format(
            date_from=date_from,
            date_to=date_to,
            filters_select_clause=action_filters.select_clause,
            matches_action_clauses=action_filters.matches_action_clauses,
            filters_having=action_filters.filters_having,
            sessions_limit="LIMIT %(offset)s, %(limit)s",
        )
        query_result = sync_execute(
            query,
            {
                **action_filters.params,
                "team_id": self.team.pk,
                "limit": limit,
                "offset": offset,
                "distinct_ids": distinct_ids,
                **date_params,
            },
        )
        result = self._parse_list_results(query_result)

        pagination = None
        if len(distinct_ids) >= limit + distinct_id_offset or len(result) == limit:
            if len(result) == limit:
                result.pop()
            pagination = {"offset": offset + len(result), "distinct_id_offset": distinct_id_offset + limit}

        self._add_person_properties(result)

        return join_with_session_recordings(self.team, result, self.filter), pagination

    def fetch_distinct_ids(
        self,
        action_filters: ActionFiltersSQL,
        date_from: str,
        date_to: str,
        date_params: Dict[str, Any],
        limit: int,
        distinct_id_offset: int,
    ) -> List[str]:
        if self.filter.distinct_id:
            persons = get_persons_by_distinct_ids(self.team.pk, [self.filter.distinct_id])
            return persons[0].distinct_ids if len(persons) > 0 else []

        person_filters, person_filter_params = parse_prop_clauses(
            self.filter.person_filter_properties, self.team.pk, allow_denormalized_props=False
        )
        return sync_execute(
            SESSIONS_DISTINCT_ID_SQL.format(
                date_from=date_from,
                date_to=date_to,
                person_filters=person_filters,
                action_filters=action_filters.matches_any_clause,
            ),
            {
                **person_filter_params,
                **action_filters.params,
                "team_id": self.team.pk,
                "distinct_id_limit": distinct_id_offset + limit,
                **date_params,
            },
        )

    def _add_person_properties(self, sessions: List[Session]):
        distinct_id_hash = {}
        for session in sessions:
            distinct_id_hash[session["distinct_id"]] = True
        distinct_ids = list(distinct_id_hash.keys())

        if len(distinct_ids) == 0:
            return

        persons = get_persons_by_distinct_ids(self.team.pk, distinct_ids)

        distinct_to_person: Dict[str, Person] = {}
        for person in persons:
            for distinct_id in person.distinct_ids:
                distinct_to_person[distinct_id] = person

        for session in sessions:
            if distinct_to_person.get(session["distinct_id"], None):
                session["email"] = distinct_to_person[session["distinct_id"]].properties.get("email")

    def _parse_list_results(self, results: List[Tuple]):
        return [
            {
                "distinct_id": result[0],
                "global_session_id": result[1],
                "length": result[2],
                "start_time": result[3],
                "end_time": result[4],
                "start_url": _process_url(result[5]),
                "end_url": _process_url(result[6]),
                "matching_events": list(sorted(set(flatten(result[7:])))),
            }
            for result in results
        ]


def format_action_filters(filter: SessionsFilter) -> ActionFiltersSQL:
    if len(filter.action_filters) == 0:
        return ActionFiltersSQL("", "", "", "", {})

    matches_action_clauses = select_clause = ""
    having_clause = []
    matches_any_clause = []

    params: Dict = {}

    for index, entity in enumerate(filter.action_filters):
        condition_sql, filter_params = format_action_filter_aggregate(entity, prepend=f"event_matcher_{index}")

        matches_action_clauses += f", ({condition_sql}) ? uuid : NULL as event_match_{index}"
        select_clause += f", groupArray(event_match_{index}) as event_match_{index}"
        having_clause.append(f"notEmpty(event_match_{index})")
        matches_any_clause.append(condition_sql)

        params = {**params, **filter_params}

    return ActionFiltersSQL(
        select_clause,
        matches_action_clauses,
        f"HAVING {' AND '.join(having_clause)}",
        f"AND ({' OR '.join(matches_any_clause)})",
        params,
    )


def format_action_filter_aggregate(entity: Entity, prepend: str):
    filter_sql, params = format_entity_filter(entity, prepend=prepend, filter_by_team=False)
    if entity.properties:
        filters, filter_params = parse_prop_clauses(
            entity.properties, prepend=prepend, team_id=None, allow_denormalized_props=False, has_person_id_joined=False
        )
        filter_sql += f" {filters}"
        params = {**params, **filter_params}

    return filter_sql, params


def _process_url(url: Optional[str]) -> Optional[str]:
    if url is not None:
        url = url.strip('"')
    if url == "":
        url = None
    return url
