from typing import Any, Dict, List, Optional, Tuple, Union, cast

from django.forms import ValidationError

from posthog.client import sync_execute
from posthog.constants import BREAKDOWN_TYPES, PropertyOperatorType
from posthog.models.cohort import Cohort
from posthog.models.cohort.util import format_filter_query
from posthog.models.entity import Entity
from posthog.models.entity.util import get_entity_filtering_params
from posthog.models.filters.filter import Filter
from posthog.models.filters.utils import GroupTypeIndex
from posthog.models.property import PropertyGroup
from posthog.models.property.util import (
    get_property_string_expr,
    get_single_or_multi_property_string_expr,
    parse_prop_grouped_clauses,
)
from posthog.models.team import Team
from posthog.models.utils import PersonPropertiesMode
from posthog.queries.column_optimizer.column_optimizer import ColumnOptimizer
from posthog.queries.groups_join_query import GroupsJoinQuery
from posthog.queries.person_distinct_id_query import get_team_distinct_ids_query
from posthog.queries.person_query import PersonQuery
from posthog.queries.session_query import SessionQuery
from posthog.queries.trends.sql import HISTOGRAM_ELEMENTS_ARRAY_OF_KEY_SQL, TOP_ELEMENTS_ARRAY_OF_KEY_SQL
from posthog.queries.util import parse_timestamps

ALL_USERS_COHORT_ID = 0


def get_breakdown_prop_values(
    filter: Filter,
    entity: Entity,
    aggregate_operation: str,
    team: Team,
    extra_params={},
    column_optimizer: Optional[ColumnOptimizer] = None,
    person_properties_mode: PersonPropertiesMode = PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
    use_all_funnel_entities: bool = False,
):
    """
    Returns the top N breakdown prop values for event/person breakdown

    e.g. for Browser with limit 3 might return ['Chrome', 'Safari', 'Firefox', 'Other']

    When dealing with a histogram though, buckets are returned instead of values.
    """
    column_optimizer = column_optimizer or ColumnOptimizer(filter, team.id)
    parsed_date_from, parsed_date_to, date_params = parse_timestamps(filter=filter, team=team)

    if not use_all_funnel_entities:
        props_to_filter = filter.property_groups.combine_property_group(
            PropertyOperatorType.AND, entity.property_groups
        )
    else:
        props_to_filter = filter.property_groups

    person_join_clauses = ""
    person_join_params: Dict = {}

    groups_join_clause = ""
    groups_join_params: Dict = {}

    sessions_join_clause = ""
    sessions_join_params: Dict = {}

    if person_properties_mode == PersonPropertiesMode.DIRECT_ON_EVENTS:
        outer_properties: Optional[PropertyGroup] = props_to_filter
        person_id_joined_alias = "e.person_id"
    else:
        outer_properties = column_optimizer.property_optimizer.parse_property_groups(props_to_filter).outer
        person_id_joined_alias = "pdi.person_id"

        person_query = PersonQuery(
            filter, team.pk, column_optimizer=column_optimizer, entity=entity if not use_all_funnel_entities else None
        )
        if person_query.is_used:
            person_subquery, person_join_params = person_query.get_query()
            person_join_clauses = f"""
                INNER JOIN ({get_team_distinct_ids_query(team.pk)}) AS pdi ON e.distinct_id = pdi.distinct_id
                INNER JOIN ({person_subquery}) person ON pdi.person_id = person.id
            """
        elif column_optimizer.is_using_cohort_propertes:
            person_join_clauses = f"""
                INNER JOIN ({get_team_distinct_ids_query(team.pk)}) AS pdi ON e.distinct_id = pdi.distinct_id
            """

        groups_join_clause, groups_join_params = GroupsJoinQuery(filter, team.pk, column_optimizer).get_join_query()

    if filter.breakdown_type == "session" or entity.math_property == "$session_duration":
        session_query, sessions_join_params = SessionQuery(filter=filter, team=team).get_query()
        sessions_join_clause = f"""
                INNER JOIN ({session_query}) AS {SessionQuery.SESSION_TABLE_ALIAS} ON {SessionQuery.SESSION_TABLE_ALIAS}.$session_id = e.$session_id
        """
    prop_filters, prop_filter_params = parse_prop_grouped_clauses(
        team_id=team.pk,
        property_group=outer_properties,
        table_name="e",
        prepend="e_brkdwn",
        person_properties_mode=person_properties_mode,
        allow_denormalized_props=True,
        person_id_joined_alias=person_id_joined_alias,
    )

    if use_all_funnel_entities:
        from posthog.queries.funnels.funnel_event_query import FunnelEventQuery

        entity_filter, entity_params = FunnelEventQuery(
            filter, team, using_person_on_events=team.actor_on_events_querying_enabled,
        )._get_entity_query()
        entity_format_params = {"entity_query": entity_filter}
    else:
        entity_params, entity_format_params = get_entity_filtering_params(
            entity=entity,
            team_id=team.pk,
            table_name="e",
            person_id_joined_alias=person_id_joined_alias,
            person_properties_mode=person_properties_mode,
        )

    value_expression = _to_value_expression(
        filter.breakdown_type,
        filter.breakdown,
        filter.breakdown_group_type_index,
        direct_on_events=True if person_properties_mode == PersonPropertiesMode.DIRECT_ON_EVENTS else False,
        cast_as_float=filter.using_histogram,
    )

    if filter.using_histogram:
        bucketing_expression = _to_bucketing_expression(cast(int, filter.breakdown_histogram_bin_count))
        elements_query = HISTOGRAM_ELEMENTS_ARRAY_OF_KEY_SQL.format(
            bucketing_expression=bucketing_expression,
            value_expression=value_expression,
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            prop_filters=prop_filters,
            aggregate_operation=aggregate_operation,
            person_join_clauses=person_join_clauses,
            groups_join_clauses=groups_join_clause,
            sessions_join_clauses=sessions_join_clause,
            **entity_format_params,
        )
    else:
        elements_query = TOP_ELEMENTS_ARRAY_OF_KEY_SQL.format(
            value_expression=value_expression,
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            prop_filters=prop_filters,
            aggregate_operation=aggregate_operation,
            person_join_clauses=person_join_clauses,
            groups_join_clauses=groups_join_clause,
            sessions_join_clauses=sessions_join_clause,
            **entity_format_params,
        )

    return sync_execute(
        elements_query,
        {
            "key": filter.breakdown,
            "limit": filter.breakdown_limit_or_default,
            "team_id": team.pk,
            "offset": filter.offset,
            "timezone": team.timezone,
            **prop_filter_params,
            **entity_params,
            **person_join_params,
            **groups_join_params,
            **sessions_join_params,
            **extra_params,
            **date_params,
        },
    )[0][0]


def _to_value_expression(
    breakdown_type: Optional[BREAKDOWN_TYPES],
    breakdown: Union[str, List[Union[str, int]], None],
    breakdown_group_type_index: Optional[GroupTypeIndex],
    direct_on_events: bool = False,
    cast_as_float: bool = False,
) -> str:
    if breakdown_type == "session":
        if breakdown == "$session_duration":
            # Return the session duration expression right away because it's already an number,
            # so it doesn't need casting for the histogram case (like the other properties)
            value_expression = f"{SessionQuery.SESSION_TABLE_ALIAS}.session_duration"
        else:
            raise ValidationError(f'Invalid breakdown "{breakdown}" for breakdown type "session"')
    elif breakdown_type == "person":
        value_expression = get_single_or_multi_property_string_expr(
            breakdown,
            query_alias=None,
            table="events" if direct_on_events else "person",
            column="person_properties" if direct_on_events else "person_props",
        )
    elif breakdown_type == "group":
        value_expression, _ = get_property_string_expr(
            table="groups",
            property_name=cast(str, breakdown),
            var="%(key)s",
            column=f"group{breakdown_group_type_index}_properties"
            if direct_on_events
            else f"group_properties_{breakdown_group_type_index}",
        )
    else:
        value_expression = get_single_or_multi_property_string_expr(
            breakdown, table="events", query_alias=None, column="properties"
        )

    if cast_as_float:
        value_expression = f"toFloat64OrNull(toString({value_expression}))"
    return f"{value_expression} AS value"


def _to_bucketing_expression(bin_count: int) -> str:
    if bin_count <= 1:
        qunatile_expression = "quantiles(0,1)(value)"
    else:
        quantiles = []
        bin_size = 1.0 / bin_count
        for i in range(bin_count + 1):
            quantiles.append(i * bin_size)

        qunatile_expression = f"quantiles({','.join([f'{quantile:.2f}' for quantile in quantiles])})(value)"

    return f"arrayCompact(arrayMap(x -> floor(x, 2), {qunatile_expression}))"


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
