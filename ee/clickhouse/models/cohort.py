import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from dateutil import parser
from django.conf import settings
from django.utils import timezone

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.sql.cohort import (
    CALCULATE_COHORT_PEOPLE_SQL,
    GET_PERSON_ID_BY_COHORT_ID,
    INSERT_PEOPLE_MATCHING_COHORT_ID_SQL,
    REMOVE_PEOPLE_NOT_MATCHING_COHORT_ID_SQL,
)
from ee.clickhouse.sql.person import (
    GET_LATEST_PERSON_DISTINCT_ID_SQL,
    GET_LATEST_PERSON_ID_SQL,
    GET_PERSON_IDS_BY_FILTER,
    INSERT_PERSON_STATIC_COHORT,
    PERSON_STATIC_COHORT_TABLE,
)
from posthog.models import Action, Cohort, Filter, Team

# temporary marker to denote when cohortpeople table started being populated
TEMP_PRECALCULATED_MARKER = parser.parse("2021-06-07T15:00:00+00:00")


def format_person_query(cohort: Cohort, **kwargs) -> Tuple[str, Dict[str, Any]]:
    filters = []
    params: Dict[str, Any] = {}

    custom_match_field = kwargs.get("custom_match_field", "person_id")

    if cohort.is_static:
        return (
            f"{custom_match_field} IN (SELECT person_id FROM {PERSON_STATIC_COHORT_TABLE} WHERE cohort_id = %(cohort_id)s AND team_id = %(team_id)s)",
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
        filters.append("{} IN {}".format(custom_match_field, GET_LATEST_PERSON_ID_SQL.format(query=query)))

    joined_filter = " OR ".join(filters)
    return joined_filter, params


def parse_action_timestamps(days: int) -> Tuple[str, Dict[str, str]]:
    curr_time = timezone.now()
    start_time = curr_time - timedelta(days=days)

    return (
        "and timestamp >= %(date_from)s AND timestamp <= %(date_to)s",
        {"date_from": start_time.strftime("%Y-%m-%d %H:%M:%S"), "date_to": curr_time.strftime("%Y-%m-%d %H:%M:%S")},
    )


def is_precalculated_query(cohort: Cohort) -> bool:
    if (
        cohort.last_calculation
        and cohort.last_calculation > TEMP_PRECALCULATED_MARKER
        and not settings.DEBUG
        and not settings.TEST
    ):
        return True
    else:
        return False


def format_filter_query(cohort: Cohort) -> Tuple[str, Dict[str, Any]]:
    is_precalculated = is_precalculated_query(cohort)
    person_query, params = get_precalculated_query(cohort) if is_precalculated else format_person_query(cohort)

    person_id_query = CALCULATE_COHORT_PEOPLE_SQL.format(
        query=person_query, latest_distinct_id_sql=GET_LATEST_PERSON_DISTINCT_ID_SQL
    )
    return person_id_query, params


def get_precalculated_query(cohort: Cohort, **kwargs) -> Tuple[str, Dict[str, Any]]:
    custom_match_field = kwargs.get("custom_match_field", "person_id")
    return (
        f"""
        {custom_match_field} IN ({GET_PERSON_ID_BY_COHORT_ID})
        """,
        {"team_id": cohort.team_id, "cohort_id": cohort.pk},
    )


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
    cohort_filter, cohort_params = format_person_query(cohort, custom_match_field="id")

    cohort_filter = GET_PERSON_IDS_BY_FILTER.format(distinct_query="AND " + cohort_filter, query="")

    insert_cohortpeople_sql = INSERT_PEOPLE_MATCHING_COHORT_ID_SQL.format(cohort_filter=cohort_filter)

    sync_execute(insert_cohortpeople_sql, {**cohort_params, "cohort_id": cohort.pk, "team_id": cohort.team_id})

    remove_cohortpeople_sql = REMOVE_PEOPLE_NOT_MATCHING_COHORT_ID_SQL.format(cohort_filter=cohort_filter)

    sync_execute(remove_cohortpeople_sql, {**cohort_params, "cohort_id": cohort.pk, "team_id": cohort.team_id})
