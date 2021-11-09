from typing import Any, Dict, List, Optional, Tuple, cast

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.cohort import format_filter_query
from ee.clickhouse.models.entity import get_entity_filtering_params
from ee.clickhouse.models.property import get_property_string_expr, parse_prop_clauses
from ee.clickhouse.models.util import PersonPropertiesMode
from ee.clickhouse.queries.column_optimizer import ColumnOptimizer
from ee.clickhouse.queries.groups_join_query import GroupsJoinQuery
from ee.clickhouse.queries.person_query import ClickhousePersonQuery
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.person import GET_TEAM_PERSON_DISTINCT_IDS
from ee.clickhouse.sql.trends.top_elements import TOP_ELEMENTS_ARRAY_OF_KEY_SQL
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters.filter import Filter
from posthog.models.property import TableWithProperties

ALL_USERS_COHORT_ID = 0


def get_breakdown_prop_values(
    filter: Filter,
    entity: Entity,
    aggregate_operation: str,
    team_id: int,
    limit: int = 25,
    extra_params={},
    column_optimizer: Optional[ColumnOptimizer] = None,
):
    "Returns the top N breakdown prop values for event/person breakdown"

    parsed_date_from, parsed_date_to, date_params = parse_timestamps(filter=filter, team_id=team_id)
    prop_filters, prop_filter_params = parse_prop_clauses(
        filter.properties + entity.properties,
        team_id,
        table_name="e",
        prepend="e_brkdwn",
        person_properties_mode=PersonPropertiesMode.EXCLUDE,
        allow_denormalized_props=True,
    )

    entity_params, entity_format_params = get_entity_filtering_params(entity, team_id, table_name="e")

    if filter.breakdown_type == "person":
        value_expression, _ = get_property_string_expr("person", cast(str, filter.breakdown), "%(key)s", "person_props")
    elif filter.breakdown_type == "group":
        value_expression, _ = get_property_string_expr(
            "groups", cast(str, filter.breakdown), "%(key)s", f"group_properties_{filter.breakdown_group_type_index}"
        )
    else:
        value_expression, _ = get_property_string_expr("events", cast(str, filter.breakdown), "%(key)s", "properties")

    person_join_clauses = ""
    person_join_params: Dict = {}
    person_query = ClickhousePersonQuery(filter, team_id, column_optimizer=column_optimizer, entity=entity)
    if person_query.is_used:
        person_subquery, person_join_params = person_query.get_query()
        person_join_clauses = f"""
            INNER JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) AS pdi ON e.distinct_id = pdi.distinct_id
            INNER JOIN ({person_subquery}) person ON pdi.person_id = person.id
        """

    groups_join_condition, groups_join_params = GroupsJoinQuery(filter, team_id, column_optimizer).get_join_query()

    elements_query = TOP_ELEMENTS_ARRAY_OF_KEY_SQL.format(
        value_expression=value_expression,
        parsed_date_from=parsed_date_from,
        parsed_date_to=parsed_date_to,
        prop_filters=prop_filters,
        aggregate_operation=aggregate_operation,
        person_join_clauses=person_join_clauses,
        groups_join_clauses=groups_join_condition,
        **entity_format_params,
    )

    return sync_execute(
        elements_query,
        {
            "key": filter.breakdown,
            "limit": limit,
            "team_id": team_id,
            "offset": filter.offset,
            **prop_filter_params,
            **entity_params,
            **person_join_params,
            **groups_join_params,
            **extra_params,
            **date_params,
        },
    )[0][0]


def _format_all_query(team_id: int, filter: Filter, **kwargs) -> Tuple[str, Dict]:
    entity = kwargs.pop("entity", None)
    parsed_date_from, parsed_date_to, date_params = parse_timestamps(
        filter=filter, team_id=team_id, table="all_events."
    )

    props_to_filter = [*filter.properties]

    if entity and isinstance(entity, Entity):
        props_to_filter = [*props_to_filter, *entity.properties]

    prop_filters, prop_filter_params = parse_prop_clauses(
        props_to_filter, team_id, prepend="all_cohort_", table_name="all_events"
    )
    query = f"""
            SELECT DISTINCT distinct_id, {ALL_USERS_COHORT_ID} as value
            FROM events all_events
            WHERE team_id = {team_id}
            {parsed_date_from}
            {parsed_date_to}
            {prop_filters}
            """
    return query, {**date_params, **prop_filter_params}


def format_breakdown_cohort_join_query(team_id: int, filter: Filter, **kwargs) -> Tuple[str, List, Dict]:
    entity = kwargs.pop("entity", None)
    cohorts = (
        Cohort.objects.filter(team_id=team_id, pk__in=[b for b in filter.breakdown if b != "all"])
        if isinstance(filter.breakdown, list)
        else Cohort.objects.filter(team_id=team_id, pk=filter.breakdown)
    )
    cohort_queries, params = _parse_breakdown_cohorts(list(cohorts))
    ids = [cohort.pk for cohort in cohorts]
    if isinstance(filter.breakdown, list) and "all" in filter.breakdown:
        all_query, all_params = _format_all_query(team_id, filter, entity=entity)
        cohort_queries.append(all_query)
        params = {**params, **all_params}
        ids.append(ALL_USERS_COHORT_ID)
    return " UNION ALL ".join(cohort_queries), ids, params


def _parse_breakdown_cohorts(cohorts: List[Cohort]) -> Tuple[List[str], Dict]:
    queries = []
    params: Dict[str, Any] = {}
    for idx, cohort in enumerate(cohorts):
        person_id_query, cohort_filter_params = format_filter_query(cohort, idx)
        params = {**params, **cohort_filter_params}
        cohort_query = person_id_query.replace(
            "SELECT distinct_id", f"SELECT distinct_id, {cohort.pk} as value", 1
        )  # only replace the first top level occurrence
        queries.append(cohort_query)
    return queries, params


def get_breakdown_cohort_name(cohort_id: int) -> str:
    if cohort_id == ALL_USERS_COHORT_ID:
        return "all users"
    else:
        return Cohort.objects.get(pk=cohort_id).name
