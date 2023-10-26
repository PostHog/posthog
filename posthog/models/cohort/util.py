import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple, Union

import structlog
from dateutil import parser
from django.conf import settings
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from posthog.client import sync_execute
from posthog.constants import PropertyOperatorType
from posthog.hogql.hogql import HogQLContext
from posthog.models import Action, Filter, Team
from posthog.models.action.util import format_action_filter
from posthog.models.async_deletion import AsyncDeletion, DeletionType
from posthog.models.cohort.cohort import Cohort
from posthog.models.cohort.sql import (
    CALCULATE_COHORT_PEOPLE_SQL,
    GET_COHORT_SIZE_SQL,
    GET_COHORTS_BY_PERSON_UUID,
    GET_PERSON_ID_BY_PRECALCULATED_COHORT_ID,
    GET_STATIC_COHORT_SIZE_SQL,
    GET_STATIC_COHORTPEOPLE_BY_PERSON_UUID,
    RECALCULATE_COHORT_BY_ID,
    STALE_COHORTPEOPLE,
)
from posthog.models.person.sql import (
    GET_LATEST_PERSON_SQL,
    GET_PERSON_IDS_BY_FILTER,
    INSERT_PERSON_STATIC_COHORT,
    PERSON_STATIC_COHORT_TABLE,
)
from posthog.models.property import Property, PropertyGroup
from posthog.queries.insight import insight_sync_execute
from posthog.queries.person_distinct_id_query import get_team_distinct_ids_query

# temporary marker to denote when cohortpeople table started being populated
TEMP_PRECALCULATED_MARKER = parser.parse("2021-06-07T15:00:00+00:00")

logger = structlog.get_logger(__name__)


def format_person_query(cohort: Cohort, index: int, hogql_context: HogQLContext) -> Tuple[str, Dict[str, Any]]:
    if cohort.is_static:
        return format_static_cohort_query(cohort, index, prepend="")

    if not cohort.properties.values:
        # No person can match an empty cohort
        return "SELECT generateUUIDv4() as id WHERE 0 = 19", {}

    from posthog.queries.cohort_query import CohortQuery

    query_builder = CohortQuery(
        Filter(
            data={"properties": cohort.properties},
            team=cohort.team,
            hogql_context=hogql_context,
        ),
        cohort.team,
        cohort_pk=cohort.pk,
    )

    query, params = query_builder.get_query()

    return query, params


def format_static_cohort_query(cohort: Cohort, index: int, prepend: str) -> Tuple[str, Dict[str, Any]]:
    cohort_id = cohort.pk
    return (
        f"SELECT person_id as id FROM {PERSON_STATIC_COHORT_TABLE} WHERE cohort_id = %({prepend}_cohort_id_{index})s AND team_id = %(team_id)s",
        {f"{prepend}_cohort_id_{index}": cohort_id},
    )


def format_precalculated_cohort_query(cohort: Cohort, index: int, prepend: str = "") -> Tuple[str, Dict[str, Any]]:
    filter_query = GET_PERSON_ID_BY_PRECALCULATED_COHORT_ID.format(index=index, prepend=prepend)
    return (
        filter_query,
        {
            f"{prepend}_cohort_id_{index}": cohort.pk,
            f"{prepend}_version_{index}": cohort.version,
        },
    )


def get_count_operator(count_operator: Optional[str]) -> str:
    if count_operator == "gte":
        return ">="
    elif count_operator == "lte":
        return "<="
    elif count_operator == "gt":
        return ">"
    elif count_operator == "lt":
        return "<"
    elif count_operator == "eq" or count_operator == "exact" or count_operator is None:
        return "="
    else:
        raise ValidationError("count_operator must be gte, lte, eq, or None")


def get_entity_query(
    event_id: Optional[str],
    action_id: Optional[int],
    team_id: int,
    group_idx: Union[int, str],
    hogql_context: HogQLContext,
) -> Tuple[str, Dict[str, str]]:
    if event_id:
        return f"event = %({f'event_{group_idx}'})s", {f"event_{group_idx}": event_id}
    elif action_id:
        action = Action.objects.get(pk=action_id, team_id=team_id)
        action_filter_query, action_params = format_action_filter(
            team_id=team_id,
            action=action,
            prepend="_{}_action".format(group_idx),
            hogql_context=hogql_context,
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
        {
            "date_from": start_time.strftime("%Y-%m-%d %H:%M:%S"),
            "date_to": curr_time.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )


def parse_cohort_timestamps(start_time: Optional[str], end_time: Optional[str]) -> Tuple[str, Dict[str, str]]:
    clause = "AND "
    params: Dict[str, str] = {}

    if start_time:
        clause += "timestamp >= %(date_from)s"

        params = {"date_from": datetime.strptime(start_time, "%Y-%m-%dT%H:%M:%S").strftime("%Y-%m-%d %H:%M:%S")}
    if end_time:
        clause += "timestamp <= %(date_to)s"
        params = {
            **params,
            "date_to": datetime.strptime(end_time, "%Y-%m-%dT%H:%M:%S").strftime("%Y-%m-%d %H:%M:%S"),
        }

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
    index: int,
    hogql_context: HogQLContext,
    id_column: str = "distinct_id",
    custom_match_field="person_id",
) -> Tuple[str, Dict[str, Any]]:
    person_query, params = format_cohort_subquery(cohort, index, hogql_context, custom_match_field=custom_match_field)

    person_id_query = CALCULATE_COHORT_PEOPLE_SQL.format(
        query=person_query,
        id_column=id_column,
        GET_TEAM_PERSON_DISTINCT_IDS=get_team_distinct_ids_query(cohort.team_id),
    )
    return person_id_query, params


def format_cohort_subquery(
    cohort: Cohort,
    index: int,
    hogql_context: HogQLContext,
    custom_match_field="person_id",
) -> Tuple[str, Dict[str, Any]]:
    is_precalculated = is_precalculated_query(cohort)
    if is_precalculated:
        query, params = format_precalculated_cohort_query(cohort, index)
    else:
        query, params = format_person_query(cohort, index, hogql_context)

    person_query = f"{custom_match_field} IN ({query})"
    return person_query, params


def get_person_ids_by_cohort_id(
    team: Team,
    cohort_id: int,
    limit: Optional[int] = None,
    offset: Optional[int] = None,
):
    from posthog.models.property.util import parse_prop_grouped_clauses

    filter = Filter(data={"properties": [{"key": "id", "value": cohort_id, "type": "cohort"}]})
    filter_query, filter_params = parse_prop_grouped_clauses(
        team_id=team.pk,
        property_group=filter.property_groups,
        table_name="pdi",
        hogql_context=filter.hogql_context,
    )

    results = insight_sync_execute(
        GET_PERSON_IDS_BY_FILTER.format(
            person_query=GET_LATEST_PERSON_SQL,
            distinct_query=filter_query,
            query="",
            GET_TEAM_PERSON_DISTINCT_IDS=get_team_distinct_ids_query(team.pk),
            offset="OFFSET %(offset)s" if offset else "",
            limit="ORDER BY _timestamp ASC LIMIT %(limit)s" if limit else "",
        ),
        {**filter_params, "team_id": team.pk, "offset": offset, "limit": limit},
        query_type="get_person_ids_by_cohort_id",
        team_id=team.pk,
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


def get_static_cohort_size(cohort: Cohort) -> Optional[int]:
    count_result = sync_execute(
        GET_STATIC_COHORT_SIZE_SQL,
        {
            "cohort_id": cohort.pk,
            "team_id": cohort.team_id,
        },
    )

    if count_result and len(count_result) and len(count_result[0]):
        return count_result[0][0]
    else:
        return None


def recalculate_cohortpeople(cohort: Cohort, pending_version: int) -> Optional[int]:
    hogql_context = HogQLContext(within_non_hogql_query=True, team_id=cohort.team_id)
    cohort_query, cohort_params = format_person_query(cohort, 0, hogql_context)

    before_count = get_cohort_size(cohort)

    if before_count:
        logger.warn(
            "Recalculating cohortpeople starting",
            team_id=cohort.team_id,
            cohort_id=cohort.pk,
            size_before=before_count,
        )

    recalcluate_cohortpeople_sql = RECALCULATE_COHORT_BY_ID.format(cohort_filter=cohort_query)

    sync_execute(
        recalcluate_cohortpeople_sql,
        {
            **cohort_params,
            **hogql_context.values,
            "cohort_id": cohort.pk,
            "team_id": cohort.team_id,
            "new_version": pending_version,
        },
        settings={"optimize_on_insert": 0},
    )

    count = get_cohort_size(cohort, override_version=pending_version)

    if count is not None and before_count is not None:
        logger.warn(
            "Recalculating cohortpeople done",
            team_id=cohort.team_id,
            cohort_id=cohort.pk,
            size_before=before_count,
            size=count,
        )

    return count


def clear_stale_cohortpeople(cohort: Cohort, before_version: int) -> None:
    if cohort.version and cohort.version > 0:
        stale_count_result = sync_execute(
            STALE_COHORTPEOPLE,
            {
                "cohort_id": cohort.pk,
                "team_id": cohort.team_id,
                "version": before_version,
            },
        )

        if stale_count_result and len(stale_count_result) and len(stale_count_result[0]):
            stale_count = stale_count_result[0][0]
            if stale_count > 0:
                # Don't do anything if it already exists
                AsyncDeletion.objects.get_or_create(
                    deletion_type=DeletionType.Cohort_stale,
                    team_id=cohort.team.pk,
                    key=f"{cohort.pk}_{before_version}",
                )


def get_cohort_size(cohort: Cohort, override_version: Optional[int] = None) -> Optional[int]:
    count_result = sync_execute(
        GET_COHORT_SIZE_SQL,
        {
            "cohort_id": cohort.pk,
            "version": override_version if override_version is not None else cohort.version,
            "team_id": cohort.team_id,
        },
    )

    if count_result and len(count_result) and len(count_result[0]):
        return count_result[0][0]
    else:
        return None


def simplified_cohort_filter_properties(cohort: Cohort, team: Team, is_negated=False) -> PropertyGroup:
    """
    'Simplifies' cohort property filters, removing team-specific context from properties.
    """
    if cohort.is_static:
        return PropertyGroup(
            type=PropertyOperatorType.AND,
            values=[Property(type="static-cohort", key="id", value=cohort.pk, negation=is_negated)],
        )

    # Cohort has been precalculated
    if is_precalculated_query(cohort):
        return PropertyGroup(
            type=PropertyOperatorType.AND,
            values=[
                Property(
                    type="precalculated-cohort",
                    key="id",
                    value=cohort.pk,
                    negation=is_negated,
                )
            ],
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
                type=PropertyOperatorType.AND,
                values=[Property(type="cohort", key="id", value=cohort.pk, negation=is_negated)],
            )

        elif property.type == "cohort":
            # If entire cohort is negated, just return the negated cohort.
            if is_negated:
                return PropertyGroup(
                    type=PropertyOperatorType.AND,
                    values=[
                        Property(
                            type="cohort",
                            key="id",
                            value=cohort.pk,
                            negation=is_negated,
                        )
                    ],
                )
            # :TRICKY: We need to ensure we don't have infinite loops in here
            # guaranteed during cohort creation
            return Filter(data={"properties": cohort.properties.to_dict()}, team=team).property_groups

    # We have person properties only
    # TODO: Handle negating a complete property group
    if is_negated:
        return PropertyGroup(
            type=PropertyOperatorType.AND,
            values=[Property(type="cohort", key="id", value=cohort.pk, negation=is_negated)],
        )
    else:
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


def get_dependent_cohorts(
    cohort: Cohort,
    using_database: str = "default",
    seen_cohorts_cache: Optional[Dict[str, Cohort]] = None,
) -> List[Cohort]:
    if seen_cohorts_cache is None:
        seen_cohorts_cache = {}

    cohorts = []
    seen_cohort_ids = set()
    seen_cohort_ids.add(cohort.id)

    queue = [prop.value for prop in cohort.properties.flat if prop.type == "cohort"]

    while queue:
        cohort_id = queue.pop()
        try:
            parsed_cohort_id = str(cohort_id)
            if parsed_cohort_id in seen_cohorts_cache:
                cohort = seen_cohorts_cache[parsed_cohort_id]
            else:
                cohort = Cohort.objects.using(using_database).get(pk=cohort_id)
                seen_cohorts_cache[parsed_cohort_id] = cohort
            if cohort.id not in seen_cohort_ids:
                cohorts.append(cohort)
                seen_cohort_ids.add(cohort.id)
                queue += [prop.value for prop in cohort.properties.flat if prop.type == "cohort"]
        except Cohort.DoesNotExist:
            continue

    return cohorts
