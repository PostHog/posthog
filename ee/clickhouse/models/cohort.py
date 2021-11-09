import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

import structlog
from dateutil import parser
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.sql.cohort import (
    CALCULATE_COHORT_PEOPLE_SQL,
    GET_COHORT_SIZE_SQL,
    GET_DISTINCT_ID_BY_ENTITY_SQL,
    GET_PERSON_ID_BY_ENTITY_COUNT_SQL,
    GET_PERSON_ID_BY_PRECALCULATED_COHORT_ID,
    INSERT_PEOPLE_MATCHING_COHORT_ID_SQL,
    REMOVE_PEOPLE_NOT_MATCHING_COHORT_ID_SQL,
)
from ee.clickhouse.sql.person import (
    GET_LATEST_PERSON_ID_SQL,
    GET_PERSON_IDS_BY_FILTER,
    GET_TEAM_PERSON_DISTINCT_IDS,
    INSERT_PERSON_STATIC_COHORT,
    PERSON_STATIC_COHORT_TABLE,
)
from posthog.models import Action, Cohort, Filter, Team
from posthog.models.property import Property

# temporary marker to denote when cohortpeople table started being populated
TEMP_PRECALCULATED_MARKER = parser.parse("2021-06-07T15:00:00+00:00")

logger = structlog.get_logger(__name__)


def format_person_query(
    cohort: Cohort, index: int, *, custom_match_field: str = "person_id"
) -> Tuple[str, Dict[str, Any]]:
    filters = []
    params: Dict[str, Any] = {}

    if cohort.is_static:
        return format_static_cohort_query(cohort.pk, index, prepend="", custom_match_field=custom_match_field)

    or_queries = []
    groups = cohort.groups

    if not groups:
        # No person can match a cohort that has no match groups
        return "0 = 19", {}

    for group_idx, group in enumerate(groups):
        if group.get("action_id") or group.get("event_id"):
            entity_query, entity_params = get_entity_cohort_subquery(cohort, group, group_idx)
            params = {**params, **entity_params}
            filters.append(entity_query)

        elif group.get("properties"):
            prop_query, prop_params = get_properties_cohort_subquery(cohort, group, group_idx)
            or_queries.append(prop_query)
            params = {**params, **prop_params}

    if len(or_queries) > 0:
        query = "AND ({})".format(" OR ".join(or_queries))
        filters.append("{} IN {}".format(custom_match_field, GET_LATEST_PERSON_ID_SQL.format(query=query)))

    joined_filter = " OR ".join(filters)
    return joined_filter, params


def format_static_cohort_query(
    cohort_id: int, index: int, prepend: str, custom_match_field: str
) -> Tuple[str, Dict[str, Any]]:
    return (
        f"{custom_match_field} IN (SELECT person_id FROM {PERSON_STATIC_COHORT_TABLE} WHERE cohort_id = %({prepend}_cohort_id_{index})s AND team_id = %(team_id)s)",
        {f"{prepend}_cohort_id_{index}": cohort_id},
    )


def format_precalculated_cohort_query(
    cohort_id: int, index: int, prepend: str = "", custom_match_field="person_id"
) -> Tuple[str, Dict[str, Any]]:
    filter_query = GET_PERSON_ID_BY_PRECALCULATED_COHORT_ID.format(index=index, prepend=prepend)
    return (
        f"""
        {custom_match_field} IN ({filter_query})
        """,
        {f"{prepend}_cohort_id_{index}": cohort_id},
    )


def get_properties_cohort_subquery(cohort: Cohort, cohort_group: Dict, group_idx: int) -> Tuple[str, Dict[str, Any]]:
    from ee.clickhouse.models.property import prop_filter_json_extract

    filter = Filter(data=cohort_group)
    params: Dict[str, Any] = {}

    query_parts = []
    for idx, prop in enumerate(filter.properties):
        if prop.type == "cohort":
            try:
                prop_cohort: Cohort = Cohort.objects.get(pk=prop.value, team_id=cohort.team_id)
            except Cohort.DoesNotExist:
                return "0 = 14", {}
            if prop_cohort.pk == cohort.pk:
                # If we've encountered a cyclic dependency (meaning this cohort depends on this cohort),
                # we treat it as satisfied for all persons
                query_parts.append("AND 11 = 11")
            else:
                person_id_query, cohort_filter_params = format_filter_query(prop_cohort, idx, "person_id")
                params.update(cohort_filter_params)
                query_parts.append(f"AND person.id IN ({person_id_query})")
        else:
            filter_query, filter_params = prop_filter_json_extract(
                prop=prop,
                idx=idx,
                prepend="{}_{}_{}_person".format(cohort.pk, group_idx, idx),
                allow_denormalized_props=False,
            )
            params.update(filter_params)
            query_parts.append(filter_query)

    return "\n".join(query_parts).replace("AND ", "", 1), params


def get_entity_cohort_subquery(cohort: Cohort, cohort_group: Dict, group_idx: int):
    event_id = cohort_group.get("event_id")
    action_id = cohort_group.get("action_id")
    days = cohort_group.get("days")
    start_time = cohort_group.get("start_date")
    end_time = cohort_group.get("end_date")
    count = cohort_group.get("count")
    count_operator = cohort_group.get("count_operator")

    date_query, date_params = get_date_query(days, start_time, end_time)
    entity_query, entity_params = _get_entity_query(event_id, action_id, cohort.team.pk, group_idx)

    if count:
        count_operator = _get_count_operator(count_operator)
        extract_person = GET_PERSON_ID_BY_ENTITY_COUNT_SQL.format(
            entity_query=entity_query,
            date_query=date_query,
            count_operator=count_operator,
            GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
        )
        params: Dict[str, Union[str, int]] = {"count": int(count), **entity_params, **date_params}
        return f"person_id IN ({extract_person})", params
    else:
        extract_person = GET_DISTINCT_ID_BY_ENTITY_SQL.format(entity_query=entity_query, date_query=date_query,)
        return f"distinct_id IN ({extract_person})", {**entity_params, **date_params}


def _get_count_operator(count_operator: Optional[str]) -> str:
    if count_operator == "gte":
        return ">="
    elif count_operator == "lte":
        return "<="
    elif count_operator == "eq" or count_operator is None:
        return "="
    else:
        raise ValidationError("count_operator must be gte, lte, eq, or None")


def _get_entity_query(
    event_id: Optional[str], action_id: Optional[int], team_id: int, group_idx: int
) -> Tuple[str, Dict[str, str]]:
    if event_id:
        return "event = %(event)s", {"event": event_id}
    elif action_id:
        action = Action.objects.get(pk=action_id, team_id=team_id)
        action_filter_query, action_params = format_action_filter(action, prepend="_{}_action".format(group_idx))
        return action_filter_query, action_params
    else:
        raise ValidationError("Cohort query requires action_id or event_id")


def get_date_query(
    days: Optional[str], start_time: Optional[str], end_time: Optional[str]
) -> Tuple[str, Dict[str, str]]:
    date_query: str = ""
    date_params: Dict[str, str] = {}
    if days:
        date_query, date_params = parse_entity_timestamps_in_days(int(days))
    elif start_time or end_time:
        date_query, date_params = parse_cohort_timestamps(start_time, end_time)

    return date_query, date_params


def parse_entity_timestamps_in_days(days: int) -> Tuple[str, Dict[str, str]]:
    curr_time = timezone.now()
    start_time = curr_time - timedelta(days=days)

    return (
        "AND timestamp >= %(date_from)s AND timestamp <= %(date_to)s",
        {"date_from": start_time.strftime("%Y-%m-%d %H:%M:%S"), "date_to": curr_time.strftime("%Y-%m-%d %H:%M:%S")},
    )


def parse_cohort_timestamps(start_time: Optional[str], end_time: Optional[str]) -> Tuple[str, Dict[str, str]]:
    clause = "AND "
    params: Dict[str, str] = {}

    if start_time:
        clause += "timestamp >= %(date_from)s"

        params = {"date_from": datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")}
    if end_time:
        clause += "timestamp <= %(date_to)s"
        params = {**params, "date_to": datetime.strptime(end_time, "%Y-%m-%dT%H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")}

    return clause, params


def is_precalculated_query(cohort: Cohort) -> bool:
    if (
        cohort.last_calculation
        and cohort.last_calculation > TEMP_PRECALCULATED_MARKER
        and settings.USE_PRECALCULATED_CH_COHORT_PEOPLE
        and not cohort.is_static  # static cohorts are handled within the regular cohort filter query path
    ):
        return True
    else:
        return False


def format_filter_query(cohort: Cohort, index: int = 0, id_column: str = "distinct_id") -> Tuple[str, Dict[str, Any]]:
    is_precalculated = is_precalculated_query(cohort)
    person_query, params = (
        format_precalculated_cohort_query(cohort.pk, index) if is_precalculated else format_person_query(cohort, index)
    )

    person_id_query = CALCULATE_COHORT_PEOPLE_SQL.format(
        query=person_query, id_column=id_column, GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS
    )
    return person_id_query, params


def get_person_ids_by_cohort_id(team: Team, cohort_id: int):
    from ee.clickhouse.models.property import parse_prop_clauses

    filters = Filter(data={"properties": [{"key": "id", "value": cohort_id, "type": "cohort"}],})
    filter_query, filter_params = parse_prop_clauses(filters.properties, team.pk, table_name="pdi")

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
    cohort_filter, cohort_params = format_person_query(cohort, 0, custom_match_field="id")

    before_count = sync_execute(GET_COHORT_SIZE_SQL, {"cohort_id": cohort.pk, "team_id": cohort.team_id})
    logger.info(
        "Recalculating cohortpeople starting",
        team_id=cohort.team_id,
        cohort_id=cohort.pk,
        size_before=before_count[0][0],
    )

    cohort_filter = GET_PERSON_IDS_BY_FILTER.format(distinct_query="AND " + cohort_filter, query="")

    insert_cohortpeople_sql = INSERT_PEOPLE_MATCHING_COHORT_ID_SQL.format(cohort_filter=cohort_filter)
    sync_execute(insert_cohortpeople_sql, {**cohort_params, "cohort_id": cohort.pk, "team_id": cohort.team_id})

    remove_cohortpeople_sql = REMOVE_PEOPLE_NOT_MATCHING_COHORT_ID_SQL.format(cohort_filter=cohort_filter)
    sync_execute(remove_cohortpeople_sql, {**cohort_params, "cohort_id": cohort.pk, "team_id": cohort.team_id})

    count = sync_execute(GET_COHORT_SIZE_SQL, {"cohort_id": cohort.pk, "team_id": cohort.team_id})
    logger.info(
        "Recalculating cohortpeople done",
        team_id=cohort.team_id,
        cohort_id=cohort.pk,
        size_before=before_count[0][0],
        size=count[0][0],
    )


def simplified_cohort_filter_properties(cohort: Cohort, team: Team) -> List[Property]:
    """
    'Simplifies' cohort property filters, removing team-specific context from properties.
    """
    from ee.clickhouse.models.cohort import is_precalculated_query

    if cohort.is_static:
        return [Property(type="static-cohort", key="id", value=cohort.pk)]

    # Cohort has been precalculated
    if is_precalculated_query(cohort):
        return [Property(type="precalculated-cohort", key="id", value=cohort.pk)]

    # Cohort can have multiple match groups.
    # Each group is either
    # 1. "user has done X in time range Y at least N times" or
    # 2. "user has properties XYZ", including belonging to another cohort
    #
    # Users who match _any_ of the groups are considered to match the cohort.
    group_filters: List[List[Property]] = []
    for group in cohort.groups:
        if group.get("action_id") or group.get("event_id"):
            # :TODO: Support hasdone as separate property type
            return [Property(type="cohort", key="id", value=cohort.pk)]
        elif group.get("properties"):
            # :TRICKY: This will recursively simplify all the properties
            filter = Filter(data=group, team=team)
            group_filters.append(filter.properties)

    if len(group_filters) > 1:
        # :TODO: Support or properties
        return [Property(type="cohort", key="id", value=cohort.pk)]
    elif len(group_filters) == 1:
        return group_filters[0]
    else:
        return []
