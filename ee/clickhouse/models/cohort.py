import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.sql.cohort import CALCULATE_COHORT_PEOPLE_SQL
from ee.clickhouse.sql.person import (
    GET_LATEST_PERSON_DISTINCT_ID_SQL,
    GET_LATEST_PERSON_ID_SQL,
    GET_PERSON_IDS_BY_FILTER,
    INSERT_PERSON_STATIC_COHORT,
    PERSON_STATIC_COHORT_TABLE,
)
from posthog.models import Action, Cohort, Filter, Team


def format_person_query(cohort: Cohort) -> Tuple[str, Dict[str, Any]]:
    filters = []
    params: Dict[str, Any] = {}

    if cohort.is_static:
        return (
            "person_id IN (SELECT person_id FROM {} WHERE cohort_id = %(cohort_id)s AND team_id = %(team_id)s)".format(
                PERSON_STATIC_COHORT_TABLE
            ),
            {"cohort_id": cohort.pk, "team_id": cohort.team_id},
        )

    or_queries = []
    for group_idx, group in enumerate(cohort.groups):
        if group.get("action_id"):
            action = Action.objects.get(pk=group["action_id"], team_id=cohort.team.pk)
            action_filter_query, action_params = format_action_filter(action, prepend="_{}_action".format(group_idx))

            date_query: str = ""
            date_params: Dict[str, str] = {}
            if group.get("days"):
                date_query, date_params = parse_action_timestamps(int(group.get("days")))

            extract_person = "SELECT distinct_id FROM events WHERE team_id = %(team_id)s {date_query} AND {query}".format(
                query=action_filter_query, date_query=date_query
            )
            params = {**params, **action_params, **date_params}
            filters.append("distinct_id IN (" + extract_person + ")")

        elif group.get("properties"):
            from ee.clickhouse.models.property import prop_filter_json_extract

            filter = Filter(data=group)
            query = ""
            for idx, prop in enumerate(filter.properties):
                filter_query, filter_params = prop_filter_json_extract(
                    prop=prop, idx=idx, prepend="{}_{}_{}_person".format(cohort.pk, group_idx, idx)
                )
                params = {**params, **filter_params}
                query += filter_query
            or_queries.append(query.replace("AND ", "", 1))
    if len(or_queries) > 0:
        query = "AND ({})".format(" OR ".join(or_queries))
        filters.append("person_id IN {}".format(GET_LATEST_PERSON_ID_SQL.format(query=query)))

    joined_filter = " OR ".join(filters)
    return joined_filter, params


def parse_action_timestamps(days: int) -> Tuple[str, Dict[str, str]]:
    curr_time = timezone.now()
    start_time = curr_time - timedelta(days=days)

    return (
        "and timestamp >= %(date_from)s AND timestamp <= %(date_to)s",
        {"date_from": start_time.strftime("%Y-%m-%d %H:%M:%S"), "date_to": curr_time.strftime("%Y-%m-%d %H:%M:%S")},
    )


def format_filter_query(cohort: Cohort) -> Tuple[str, Dict[str, Any]]:
    person_query, params = format_person_query(cohort)
    person_id_query = CALCULATE_COHORT_PEOPLE_SQL.format(
        query=person_query, latest_distinct_id_sql=GET_LATEST_PERSON_DISTINCT_ID_SQL
    )
    return person_id_query, params


def get_person_ids_by_cohort_id(team: Team, cohort_id: int):
    from ee.clickhouse.models.property import parse_prop_clauses

    filters = Filter(data={"properties": [{"key": "id", "value": cohort_id, "type": "cohort"}],})
    filter_query, filter_params = parse_prop_clauses(filters.properties, team.pk, table_name="pid")

    results = sync_execute(GET_PERSON_IDS_BY_FILTER.format(distinct_query=filter_query, query=""), filter_params,)

    return [str(row[0]) for row in results]


def insert_static_cohort(person_uuids: List[Optional[uuid.UUID]], cohort_id: int, team: Team):
    persons = (
        {
            "id": str(uuid.uuid4()),
            "person_id": str(person_uuid),
            "cohort_id": cohort_id,
            "team_id": team.pk,
            "_timestamp": datetime.now(),
        }
        for person_uuid in person_uuids
    )
    sync_execute(INSERT_PERSON_STATIC_COHORT, persons)


def recalculate_cohortpeople(cohort: Cohort):
    cohort_filter, cohort_params = format_person_query(cohort)

    INSERT_PEOPLE_MATCHING_COHORT_ID_SQL = """
    INSERT INTO cohortpeople
        SELECT id, %(cohort_id)s as cohort_id, %(team_id)s as team_id, 1 as _sign
        FROM (
            SELECT id, argMax(properties, person._timestamp) as properties, sum(is_deleted) as is_deleted FROM person WHERE team_id = %(team_id)s GROUP BY id
        ) as person
        LEFT JOIN cohortpeople ON (person.id = cohortpeople.person_id)
        WHERE cohortpeople.person_id = '00000000-0000-0000-0000-000000000000'
        AND person.is_deleted = 0
        AND {cohort_filter}
    """.format(
        cohort_filter=cohort_filter
    )

    sync_execute(INSERT_PERSON_STATIC_COHORT, {**cohort_params, "cohort_id": cohort.pk})

    REMOVE_PEOPLE_NOT_MATCHING_COHORT_ID_SQL = """
    INSERT INTO cohortpeople
    SELECT person_id, cohort_id, %(team_id)s as team_id,  -1 as _sign
    FROM cohortpeople
    JOIN (
        SELECT id, argMax(properties, person._timestamp) as properties, sum(is_deleted) as is_deleted FROM person WHERE team_id = %(team_id)s GROUP BY id
    ) as person ON (person.id = cohortpeople.person_id)
    WHERE cohort_id = %(cohort_id)s
    AND 
        (
            person.is_deleted = 1 OR NOT ({cohort_filter})
        )
    """.format(
        cohort_filter=cohort_filter
    )

    sync_execute(REMOVE_PEOPLE_NOT_MATCHING_COHORT_ID_SQL, {**cohort_params, "cohort_id": cohort.pk})
