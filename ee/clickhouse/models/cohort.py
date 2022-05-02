import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import structlog
from dateutil import parser
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from ee.clickhouse.sql.cohort import (
    CALCULATE_COHORT_PEOPLE_SQL,
    GET_COHORT_SIZE_SQL,
    GET_COHORTS_BY_PERSON_UUID,
    GET_DISTINCT_ID_BY_ENTITY_SQL,
    GET_PERSON_ID_BY_ENTITY_COUNT_SQL,
    GET_PERSON_ID_BY_PRECALCULATED_COHORT_ID,
    GET_STATIC_COHORTPEOPLE_BY_PERSON_UUID,
    INSERT_PEOPLE_MATCHING_COHORT_ID_SQL,
    REMOVE_PEOPLE_NOT_MATCHING_COHORT_ID_SQL,
)
from ee.clickhouse.sql.person import (
    GET_LATEST_PERSON_ID_SQL,
    GET_PERSON_IDS_BY_FILTER,
    INSERT_PERSON_STATIC_COHORT,
    PERSON_STATIC_COHORT_TABLE,
)
from posthog.client import sync_execute
from posthog.constants import PropertyOperatorType
from posthog.models import Action, Cohort, Filter, Team
from posthog.models.action.util import format_action_filter
from posthog.models.property import Property, PropertyGroup
from posthog.queries.person_distinct_id_query import get_team_distinct_ids_query

# temporary marker to denote when cohortpeople table started being populated
TEMP_PRECALCULATED_MARKER = parser.parse("2021-06-07T15:00:00+00:00")

logger = structlog.get_logger(__name__)


def format_person_query(
    cohort: Cohort,
    index: int,
    *,
    custom_match_field: str = "person_id",
    cohorts_seen: Optional[Set[int]] = None,
    using_new_query: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    if cohort.is_static:
        return format_static_cohort_query(cohort.pk, index, prepend="", custom_match_field=custom_match_field)

    if using_new_query:
        if not cohort.properties.values:
            # No person can match an empty cohort
            return "0 = 19", {}

        from ee.clickhouse.queries.cohort_query import CohortQuery

        query, params = CohortQuery(
            Filter(data={"properties": cohort.properties}), cohort.team, cohort_pk=cohort.pk, cohorts_seen=cohorts_seen
        ).get_query()

        return f"{custom_match_field} IN ({query})", params

    else:
        filters = []
        params = {}

        or_queries = []
        groups = cohort.groups

        if not groups:
            # No person can match a cohort that has no match groups
            return "0 = 19", {}

        for group_idx, group in enumerate(groups):
            if group.get("action_id") or group.get("event_id"):
                entity_query, entity_params = get_entity_cohort_subquery(cohort, group, group_idx, custom_match_field)
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
    # Cohorts don't yet support OR filters
    for idx, prop in enumerate(filter.property_groups.flat):
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


def get_entity_cohort_subquery(
    cohort: Cohort, cohort_group: Dict, group_idx: int, custom_match_field: str = "person_id"
):
    event_id = cohort_group.get("event_id")
    action_id = cohort_group.get("action_id")
    days = cohort_group.get("days")
    start_time = cohort_group.get("start_date")
    end_time = cohort_group.get("end_date")
    count = cohort_group.get("count")
    count_operator = cohort_group.get("count_operator")

    date_query, date_params = get_date_query(days, start_time, end_time)
    entity_query, entity_params = get_entity_query(event_id, action_id, cohort.team.pk, group_idx)

    if count is not None:

        is_negation = (
            count_operator == "eq" or count_operator == "lte"
        ) and count == 0  # = 0 means all people who never performed the event

        count_operator = get_count_operator(count_operator)
        pdi_query = get_team_distinct_ids_query(cohort.team_id)
        extract_person = GET_PERSON_ID_BY_ENTITY_COUNT_SQL.format(
            entity_query=entity_query,
            date_query=date_query,
            GET_TEAM_PERSON_DISTINCT_IDS=pdi_query,
            count_condition="" if is_negation else f"HAVING count(*) {count_operator} %(count)s",
        )

        params: Dict[str, Union[str, int]] = {"count": int(count), **entity_params, **date_params}

        return f"{'NOT' if is_negation else ''} {custom_match_field} IN ({extract_person})", params
    else:
        extract_person = GET_DISTINCT_ID_BY_ENTITY_SQL.format(entity_query=entity_query, date_query=date_query,)
        return f"distinct_id IN ({extract_person})", {**entity_params, **date_params}


def get_count_operator(count_operator: Optional[str]) -> str:
    if count_operator == "gte":
        return ">="
    elif count_operator == "lte":
        return "<="
    elif count_operator == "eq" or count_operator is None:
        return "="
    else:
        raise ValidationError("count_operator must be gte, lte, eq, or None")


def get_entity_query(
    event_id: Optional[str], action_id: Optional[int], team_id: int, group_idx: Union[int, str]
) -> Tuple[str, Dict[str, str]]:
    if event_id:
        return f"event = %({f'event_{group_idx}'})s", {f"event_{group_idx}": event_id}
    elif action_id:
        action = Action.objects.get(pk=action_id, team_id=team_id)
        action_filter_query, action_params = format_action_filter(
            team_id=team_id, action=action, prepend="_{}_action".format(group_idx)
        )
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


def format_filter_query(
    cohort: Cohort,
    index: int = 0,
    id_column: str = "distinct_id",
    cohorts_seen: Optional[Set[int]] = None,
    using_new_query: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    person_query, params = format_cohort_subquery(
        cohort, index, custom_match_field="person_id", cohorts_seen=cohorts_seen, using_new_query=using_new_query
    )

    person_id_query = CALCULATE_COHORT_PEOPLE_SQL.format(
        query=person_query,
        id_column=id_column,
        GET_TEAM_PERSON_DISTINCT_IDS=get_team_distinct_ids_query(cohort.team_id),
    )
    return person_id_query, params


def format_cohort_subquery(
    cohort: Cohort,
    index: int,
    custom_match_field="person_id",
    cohorts_seen: Optional[Set[int]] = None,
    using_new_query: bool = False,
) -> Tuple[str, Dict[str, Any]]:
    is_precalculated = is_precalculated_query(cohort)
    person_query, params = (
        format_precalculated_cohort_query(cohort.pk, index, custom_match_field=custom_match_field)
        if is_precalculated
        else format_person_query(
            cohort,
            index,
            custom_match_field=custom_match_field,
            cohorts_seen=cohorts_seen,
            using_new_query=using_new_query,
        )
    )
    return person_query, params


def get_person_ids_by_cohort_id(team: Team, cohort_id: int, limit: Optional[int] = None, offset: Optional[int] = None):
    from ee.clickhouse.models.property import parse_prop_grouped_clauses

    filters = Filter(data={"properties": [{"key": "id", "value": cohort_id, "type": "cohort"}],})
    filter_query, filter_params = parse_prop_grouped_clauses(
        team_id=team.pk, property_group=filters.property_groups, table_name="pdi"
    )

    results = sync_execute(
        GET_PERSON_IDS_BY_FILTER.format(
            distinct_query=filter_query,
            query="",
            GET_TEAM_PERSON_DISTINCT_IDS=get_team_distinct_ids_query(team.pk),
            offset="OFFSET %(offset)s" if offset else "",
            limit="ORDER BY _timestamp ASC LIMIT %(limit)s" if limit else "",
        ),
        {**filter_params, "team_id": team.pk, "offset": offset, "limit": limit},
    )

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


def recalculate_cohortpeople_with_new_query(cohort: Cohort) -> Optional[int]:
    cohort_filter, cohort_params = format_person_query(cohort, 0, custom_match_field="id", using_new_query=True)

    count = sync_execute(
        f"""
        SELECT COUNT(1)
        FROM (
            SELECT id, argMax(properties, person._timestamp) as properties, sum(is_deleted) as is_deleted FROM person WHERE team_id = %(team_id)s GROUP BY id
        ) as person
        WHERE {cohort_filter}
        """,
        {**cohort_params, "team_id": cohort.team_id, "cohort_id": cohort.pk},
    )[0][0]

    return count


def recalculate_cohortpeople(cohort: Cohort) -> Optional[int]:

    # use the new query if
    # 1: testing
    # 2: behavioral cohort is a new type (even if new querying is disabled for team so that errors don't happen)
    # 3: the team is whitelisted for new querying
    should_use_new_query = (
        settings.TEST or (cohort.has_complex_behavioral_filter) or cohort.team.behavioral_cohort_querying_enabled
    )
    cohort_filter, cohort_params = format_person_query(
        cohort, 0, custom_match_field="id", using_new_query=should_use_new_query
    )

    before_count = sync_execute(GET_COHORT_SIZE_SQL, {"cohort_id": cohort.pk, "team_id": cohort.team_id})
    logger.info(
        "Recalculating cohortpeople starting",
        team_id=cohort.team_id,
        cohort_id=cohort.pk,
        size_before=before_count[0][0],
    )

    cohort_filter = GET_PERSON_IDS_BY_FILTER.format(
        distinct_query="AND " + cohort_filter,
        query="",
        offset="",
        limit="",
        GET_TEAM_PERSON_DISTINCT_IDS=get_team_distinct_ids_query(cohort.team_id),
    )

    insert_cohortpeople_sql = INSERT_PEOPLE_MATCHING_COHORT_ID_SQL.format(cohort_filter=cohort_filter)
    sync_execute(insert_cohortpeople_sql, {**cohort_params, "cohort_id": cohort.pk, "team_id": cohort.team_id})

    remove_cohortpeople_sql = REMOVE_PEOPLE_NOT_MATCHING_COHORT_ID_SQL.format(cohort_filter=cohort_filter)
    sync_execute(remove_cohortpeople_sql, {**cohort_params, "cohort_id": cohort.pk, "team_id": cohort.team_id})

    count_result = sync_execute(GET_COHORT_SIZE_SQL, {"cohort_id": cohort.pk, "team_id": cohort.team_id})

    if count_result and len(count_result) and len(count_result[0]):
        count = count_result[0][0]

        logger.info(
            "Recalculating cohortpeople done",
            team_id=cohort.team_id,
            cohort_id=cohort.pk,
            size_before=before_count[0][0],
            size=count,
        )
        return count

    return None


def simplified_cohort_filter_properties(cohort: Cohort, team: Team) -> PropertyGroup:
    """
    'Simplifies' cohort property filters, removing team-specific context from properties.
    """
    from ee.clickhouse.models.cohort import is_precalculated_query

    if cohort.is_static:
        return PropertyGroup(
            type=PropertyOperatorType.AND, values=[Property(type="static-cohort", key="id", value=cohort.pk)]
        )

    # Cohort has been precalculated
    if is_precalculated_query(cohort):
        return PropertyGroup(
            type=PropertyOperatorType.AND, values=[Property(type="precalculated-cohort", key="id", value=cohort.pk)]
        )

    # Cohort can have multiple match groups.
    # Each group is either
    # 1. "user has done X in time range Y at least N times" or
    # 2. "user has properties XYZ", including belonging to another cohort
    #
    # Users who match _any_ of the groups are considered to match the cohort.

    for property in cohort.properties.flat:
        if property.type == "behavioral":
            # TODO: Support behavioral property type in other insights
            return PropertyGroup(
                type=PropertyOperatorType.AND, values=[Property(type="cohort", key="id", value=cohort.pk)]
            )

        elif property.type == "cohort":
            # :TRICKY: We need to ensure we don't have infinite loops in here
            # guaranteed during cohort creation
            return Filter(data={"properties": cohort.properties.to_dict()}, team=team).property_groups

    return cohort.properties


def _get_cohort_ids_by_person_uuid(uuid: str, team_id: int) -> List[int]:
    res = sync_execute(GET_COHORTS_BY_PERSON_UUID, {"person_id": uuid, "team_id": team_id})
    return [row[0] for row in res]


def _get_static_cohort_ids_by_person_uuid(uuid: str, team_id: int) -> List[int]:
    res = sync_execute(GET_STATIC_COHORTPEOPLE_BY_PERSON_UUID, {"person_id": uuid, "team_id": team_id})
    return [row[0] for row in res]


def get_all_cohort_ids_by_person_uuid(uuid: str, team_id: int) -> List[int]:
    cohort_ids = _get_cohort_ids_by_person_uuid(uuid, team_id)
    static_cohort_ids = _get_static_cohort_ids_by_person_uuid(uuid, team_id)
    return [*cohort_ids, *static_cohort_ids]
