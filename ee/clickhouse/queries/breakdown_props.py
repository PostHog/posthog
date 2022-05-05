from typing import Any, Dict, List, Optional, Tuple, Union, cast

from ee.clickhouse.models.cohort import format_filter_query
from ee.clickhouse.models.entity import get_entity_filtering_params
from ee.clickhouse.models.property import (
    get_property_string_expr,
    get_single_or_multi_property_string_expr,
    parse_prop_grouped_clauses,
)
from ee.clickhouse.queries.column_optimizer import EnterpriseColumnOptimizer
from ee.clickhouse.queries.groups_join_query import GroupsJoinQuery
from ee.clickhouse.sql.trends.top_elements import TOP_ELEMENTS_ARRAY_OF_KEY_SQL
from posthog.client import sync_execute
from posthog.constants import BREAKDOWN_TYPES, PropertyOperatorType
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters.filter import Filter
from posthog.models.filters.utils import GroupTypeIndex
from posthog.models.team import Team
from posthog.models.utils import PersonPropertiesMode
from posthog.queries.person_distinct_id_query import get_team_distinct_ids_query
from posthog.queries.person_query import PersonQuery
from posthog.queries.util import parse_timestamps

ALL_USERS_COHORT_ID = 0


def get_breakdown_prop_values(
    filter: Filter,
    entity: Entity,
    aggregate_operation: str,
    team: Team,
    extra_params={},
    column_optimizer: Optional[EnterpriseColumnOptimizer] = None,
):
    """
    Returns the top N breakdown prop values for event/person breakdown

    e.g. for Browser with limit 3 might return ['Chrome', 'Safari', 'Firefox', 'Other']
    """
    column_optimizer = column_optimizer or EnterpriseColumnOptimizer(filter, team.id)
    parsed_date_from, parsed_date_to, date_params = parse_timestamps(filter=filter, team=team)

    props_to_filter = filter.property_groups.combine_property_group(PropertyOperatorType.AND, entity.property_groups)
    outer_properties = column_optimizer.property_optimizer.parse_property_groups(props_to_filter).outer

    prop_filters, prop_filter_params = parse_prop_grouped_clauses(
        team_id=team.pk,
        property_group=outer_properties,
        table_name="e",
        prepend="e_brkdwn",
        person_properties_mode=PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
        allow_denormalized_props=True,
        person_id_joined_alias="pdi.person_id",
    )

    entity_params, entity_format_params = get_entity_filtering_params(entity=entity, team_id=team.pk, table_name="e")

    value_expression = _to_value_expression(filter.breakdown_type, filter.breakdown, filter.breakdown_group_type_index)

    person_join_clauses = ""
    person_join_params: Dict = {}
    person_query = PersonQuery(filter, team.pk, column_optimizer=column_optimizer, entity=entity)
    if person_query.is_used:
        person_subquery, person_join_params = person_query.get_query()
        person_join_clauses = f"""
            INNER JOIN ({get_team_distinct_ids_query(team.pk)}) AS pdi ON e.distinct_id = pdi.distinct_id
            INNER JOIN ({person_subquery}) person ON pdi.person_id = person.id
        """

    groups_join_condition, groups_join_params = GroupsJoinQuery(filter, team.pk, column_optimizer).get_join_query()

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
            "limit": filter.breakdown_limit_or_default,
            "team_id": team.pk,
            "offset": filter.offset,
            "timezone": team.timezone_for_charts,
            **prop_filter_params,
            **entity_params,
            **person_join_params,
            **groups_join_params,
            **extra_params,
            **date_params,
        },
    )[0][0]


def _to_value_expression(
    breakdown_type: Optional[BREAKDOWN_TYPES],
    breakdown: Union[str, List[Union[str, int]], None],
    breakdown_group_type_index: Optional[GroupTypeIndex],
) -> str:
    if breakdown_type == "person":
        return get_single_or_multi_property_string_expr(breakdown, table="person", query_alias="value")
    elif breakdown_type == "group":
        value_expression, _ = get_property_string_expr(
            table="groups",
            property_name=cast(str, breakdown),
            var="%(key)s",
            column=f"group_properties_{breakdown_group_type_index}",
        )
        return f"{value_expression} AS value"
    else:
        return get_single_or_multi_property_string_expr(breakdown, table="events", query_alias="value")


def _format_all_query(team: Team, filter: Filter, **kwargs) -> Tuple[str, Dict]:
    entity = kwargs.pop("entity", None)
    parsed_date_from, parsed_date_to, date_params = parse_timestamps(filter=filter, team=team, table="all_events.")

    props_to_filter = filter.property_groups

    if entity and isinstance(entity, Entity):
        props_to_filter = props_to_filter.combine_property_group(PropertyOperatorType.AND, entity.property_groups)

    prop_filters, prop_filter_params = parse_prop_grouped_clauses(
        team_id=team.pk, property_group=props_to_filter, prepend="all_cohort_", table_name="all_events",
    )
    query = f"""
            SELECT DISTINCT distinct_id, {ALL_USERS_COHORT_ID} as value
            FROM events all_events
            WHERE team_id = {team.pk}
            {parsed_date_from}
            {parsed_date_to}
            {prop_filters}
            """
    return query, {**date_params, **prop_filter_params}


def format_breakdown_cohort_join_query(team: Team, filter: Filter, **kwargs) -> Tuple[str, List, Dict]:
    entity = kwargs.pop("entity", None)
    cohorts = (
        Cohort.objects.filter(team_id=team.pk, pk__in=[b for b in filter.breakdown if b != "all"])
        if isinstance(filter.breakdown, list)
        else Cohort.objects.filter(team_id=team.pk, pk=filter.breakdown)
    )
    cohort_queries, params = _parse_breakdown_cohorts(list(cohorts))
    ids = [cohort.pk for cohort in cohorts]
    if isinstance(filter.breakdown, list) and "all" in filter.breakdown:
        all_query, all_params = _format_all_query(team, filter, entity=entity)
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
