from typing import Any, Optional, Union, cast

from django.forms import ValidationError

from posthog.schema import PersonsOnEventsMode

from posthog.hogql.hogql import HogQLContext

from posthog.constants import BREAKDOWN_TYPES, MONTHLY_ACTIVE, WEEKLY_ACTIVE, PropertyOperatorType
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
from posthog.queries.column_optimizer.column_optimizer import ColumnOptimizer
from posthog.queries.groups_join_query import GroupsJoinQuery
from posthog.queries.insight import insight_sync_execute
from posthog.queries.person_distinct_id_query import get_team_distinct_ids_query
from posthog.queries.person_on_events_v2_sql import PERSON_DISTINCT_ID_OVERRIDES_JOIN_SQL
from posthog.queries.person_query import PersonQuery
from posthog.queries.query_date_range import QueryDateRange
from posthog.queries.trends.sql import HISTOGRAM_ELEMENTS_ARRAY_OF_KEY_SQL, TOP_ELEMENTS_ARRAY_OF_KEY_SQL
from posthog.queries.util import PersonPropertiesMode, alias_poe_mode_for_legacy
from posthog.session_recordings.queries.session_query import SessionQuery

ALL_USERS_COHORT_ID = 0


def get_breakdown_prop_values(
    filter: Filter,
    entity: Entity,
    aggregate_operation: str,
    team: Team,
    extra_params=None,
    column_optimizer: Optional[ColumnOptimizer] = None,
    person_properties_mode: PersonPropertiesMode = PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
    use_all_funnel_entities: bool = False,
) -> tuple[list[Any], bool]:
    """
    Returns the top N breakdown prop values for event/person breakdown

    e.g. for Browser with limit 3 might return ['Chrome', 'Safari', 'Firefox', 'Other']

    When dealing with a histogram though, buckets are returned instead of values.
    """
    if extra_params is None:
        extra_params = {}
    column_optimizer = column_optimizer or ColumnOptimizer(filter, team.id)

    date_params = {}
    query_date_range = QueryDateRange(filter=filter, team=team, should_round=False)
    parsed_date_from, date_from_params = query_date_range.date_from
    parsed_date_to, date_to_params = query_date_range.date_to
    date_params.update(date_from_params)
    date_params.update(date_to_params)

    if not use_all_funnel_entities:
        props_to_filter = filter.property_groups.combine_property_group(
            PropertyOperatorType.AND, entity.property_groups
        )
    else:
        props_to_filter = filter.property_groups

    person_join_clauses = ""
    person_join_params: dict = {}

    groups_join_clause = ""
    groups_join_params: dict = {}

    sessions_join_clause = ""
    sessions_join_params: dict = {}

    null_person_filter = (
        f"AND notEmpty(e.person_id)"
        if alias_poe_mode_for_legacy(team.person_on_events_mode) != PersonsOnEventsMode.DISABLED
        else ""
    )

    if person_properties_mode == PersonPropertiesMode.DIRECT_ON_EVENTS:
        outer_properties: Optional[PropertyGroup] = props_to_filter
        person_id_joined_alias = "e.person_id"

        groups_join_clause, groups_join_params = GroupsJoinQuery(filter, team.pk, column_optimizer).get_join_query()
    else:
        outer_properties = (
            column_optimizer.property_optimizer.parse_property_groups(props_to_filter).outer
            if person_properties_mode != PersonPropertiesMode.DIRECT_ON_EVENTS_WITH_POE_V2
            else props_to_filter
        )
        person_id_joined_alias = (
            "pdi.person_id"
            if person_properties_mode != PersonPropertiesMode.DIRECT_ON_EVENTS_WITH_POE_V2
            else "if(notEmpty(overrides.distinct_id), overrides.person_id, e.person_id)"
        )

        person_query = PersonQuery(
            filter,
            team.pk,
            column_optimizer=column_optimizer,
            entity=entity if not use_all_funnel_entities else None,
        )
        if person_properties_mode == PersonPropertiesMode.DIRECT_ON_EVENTS_WITH_POE_V2:
            person_join_clauses = PERSON_DISTINCT_ID_OVERRIDES_JOIN_SQL.format(
                event_table_alias="e", person_overrides_table_alias="overrides"
            )
        elif person_query.is_used:
            person_subquery, person_join_params = person_query.get_query()
            person_join_clauses = f"""
                INNER JOIN ({get_team_distinct_ids_query(team.pk)}) AS pdi ON e.distinct_id = pdi.distinct_id
                INNER JOIN ({person_subquery}) person ON pdi.person_id = person.id
            """
        elif entity.math in (WEEKLY_ACTIVE, MONTHLY_ACTIVE) or column_optimizer.is_using_cohort_propertes:
            person_join_clauses = f"""
                INNER JOIN ({get_team_distinct_ids_query(team.pk)}) AS pdi ON e.distinct_id = pdi.distinct_id
            """

        groups_join_clause, groups_join_params = GroupsJoinQuery(filter, team.pk, column_optimizer).get_join_query()

    session_query = SessionQuery(filter=filter, team=team)
    if session_query.is_used:
        session_query_clause, sessions_join_params = session_query.get_query()
        sessions_join_clause = f"""
                INNER JOIN ({session_query_clause}) AS {SessionQuery.SESSION_TABLE_ALIAS} ON {SessionQuery.SESSION_TABLE_ALIAS}."$session_id" = e."$session_id"
        """
    prop_filters, prop_filter_params = parse_prop_grouped_clauses(
        team_id=team.pk,
        property_group=outer_properties,
        table_name="e",
        prepend="e_brkdwn",
        person_properties_mode=person_properties_mode,
        allow_denormalized_props=True,
        person_id_joined_alias=person_id_joined_alias,
        hogql_context=filter.hogql_context,
    )

    if use_all_funnel_entities:
        from posthog.queries.funnels.funnel_event_query import FunnelEventQuery

        entity_filter, entity_params = FunnelEventQuery(
            filter,
            team,
            person_on_events_mode=alias_poe_mode_for_legacy(team.person_on_events_mode),
        )._get_entity_query()
        entity_format_params = {"entity_query": entity_filter}
    else:
        entity_params, entity_format_params = get_entity_filtering_params(
            allowed_entities=[entity],
            team_id=team.pk,
            table_name="e",
            person_id_joined_alias=person_id_joined_alias,
            person_properties_mode=person_properties_mode,
            hogql_context=filter.hogql_context,
        )

    breakdown_expression, breakdown_params = _to_value_expression(
        filter.breakdown_type,
        filter.breakdown,
        filter.breakdown_group_type_index,
        filter.hogql_context,
        filter.breakdown_normalize_url,
        direct_on_events=person_properties_mode
        in [
            PersonPropertiesMode.DIRECT_ON_EVENTS,
            PersonPropertiesMode.DIRECT_ON_EVENTS_WITH_POE_V2,
        ],
        cast_as_float=filter.using_histogram,
    )

    sample_clause = "SAMPLE %(sampling_factor)s" if filter.sampling_factor else ""
    sampling_params = {"sampling_factor": filter.sampling_factor}

    if filter.using_histogram:
        bucketing_expression = _to_bucketing_expression(cast(int, filter.breakdown_histogram_bin_count))
        elements_query = HISTOGRAM_ELEMENTS_ARRAY_OF_KEY_SQL.format(
            bucketing_expression=bucketing_expression,
            breakdown_expression=breakdown_expression,
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            prop_filters=prop_filters,
            aggregate_operation=aggregate_operation,
            person_join_clauses=person_join_clauses,
            groups_join_clauses=groups_join_clause,
            sessions_join_clauses=sessions_join_clause,
            null_person_filter=null_person_filter,
            sample_clause=sample_clause,
            **entity_format_params,
        )
    else:
        elements_query = TOP_ELEMENTS_ARRAY_OF_KEY_SQL.format(
            breakdown_expression=breakdown_expression,
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            prop_filters=prop_filters,
            aggregate_operation=aggregate_operation,
            person_join_clauses=person_join_clauses,
            groups_join_clauses=groups_join_clause,
            sessions_join_clauses=sessions_join_clause,
            null_person_filter=null_person_filter,
            sample_clause=sample_clause,
            **entity_format_params,
        )

    response = insight_sync_execute(
        elements_query,
        {
            "key": filter.breakdown,
            "limit": filter.breakdown_limit_or_default + 1,
            "team_id": team.pk,
            "offset": filter.offset,
            "timezone": team.timezone,
            **prop_filter_params,
            **entity_params,
            **breakdown_params,
            **person_join_params,
            **groups_join_params,
            **sessions_join_params,
            **extra_params,
            **date_params,
            **sampling_params,
            **filter.hogql_context.values,
        },
        query_type="get_breakdown_prop_values",
        filter=filter,
        team_id=team.pk,
    )

    if filter.using_histogram:
        return response[0][0], False
    else:
        return [row[0] for row in response[0 : filter.breakdown_limit_or_default]], len(
            response
        ) > filter.breakdown_limit_or_default


def _to_value_expression(
    breakdown_type: Optional[BREAKDOWN_TYPES],
    breakdown: Union[str, list[Union[str, int]], None],
    breakdown_group_type_index: Optional[GroupTypeIndex],
    hogql_context: HogQLContext,
    breakdown_normalize_url: bool = False,
    direct_on_events: bool = False,
    cast_as_float: bool = False,
) -> tuple[str, dict]:
    params: dict[str, Any] = {}
    if breakdown_type == "session":
        if breakdown == "$session_duration":
            # Return the session duration expression right away because it's already an number,
            # so it doesn't need casting for the histogram case (like the other properties)
            value_expression = f"{SessionQuery.SESSION_TABLE_ALIAS}.session_duration"
        else:
            raise ValidationError(f'Invalid breakdown "{breakdown}" for breakdown type "session"')
    elif breakdown_type == "person":
        value_expression, params = get_single_or_multi_property_string_expr(
            breakdown,
            query_alias=None,
            table="events" if direct_on_events else "person",
            column="person_properties" if direct_on_events else "person_props",
            allow_denormalized_props=True,
            materialised_table_column="person_properties" if direct_on_events else "properties",
        )
    elif breakdown_type == "group":
        value_expression, _ = get_property_string_expr(
            table="events" if direct_on_events else "groups",
            property_name=cast(str, breakdown),
            var="%(key)s",
            column=(
                f"group{breakdown_group_type_index}_properties"
                if direct_on_events
                else f"group_properties_{breakdown_group_type_index}"
            ),
            materialised_table_column=(
                f"group{breakdown_group_type_index}_properties" if direct_on_events else "group_properties"
            ),
        )
    elif breakdown_type == "hogql":
        from posthog.hogql.hogql import translate_hogql

        if isinstance(breakdown, list):
            expressions = [translate_hogql(exp, hogql_context) for exp in breakdown]
            value_expression = f"array({','.join(expressions)})"
        else:
            value_expression = translate_hogql(cast(str, breakdown), hogql_context)
    else:
        value_expression, params = get_single_or_multi_property_string_expr(
            breakdown,
            table="events",
            query_alias=None,
            column="properties",
            normalize_url=breakdown_normalize_url,
        )

    if cast_as_float:
        value_expression = f"toFloat64OrNull(toString({value_expression}))"

    return f"{value_expression} AS value", params


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


def _format_all_query(team: Team, filter: Filter, **kwargs) -> tuple[str, dict]:
    entity = kwargs.pop("entity", None)

    date_params = {}
    query_date_range = QueryDateRange(filter=filter, team=team, table="all_events", should_round=False)
    parsed_date_from, date_from_params = query_date_range.date_from
    parsed_date_to, date_to_params = query_date_range.date_to
    date_params.update(date_from_params)
    date_params.update(date_to_params)

    props_to_filter = filter.property_groups

    if entity and isinstance(entity, Entity):
        props_to_filter = props_to_filter.combine_property_group(PropertyOperatorType.AND, entity.property_groups)

    prop_filters, prop_filter_params = parse_prop_grouped_clauses(
        team_id=team.pk,
        property_group=props_to_filter,
        prepend="all_cohort_",
        table_name="all_events",
        hogql_context=filter.hogql_context,
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


def format_breakdown_cohort_join_query(team: Team, filter: Filter, **kwargs) -> tuple[str, list, dict]:
    entity = kwargs.pop("entity", None)
    cohorts = (
        Cohort.objects.filter(team__project_id=team.project_id, pk__in=[b for b in filter.breakdown if b != "all"])
        if isinstance(filter.breakdown, list)
        else Cohort.objects.filter(team__project_id=team.project_id, pk=filter.breakdown)
    )
    cohort_queries, params = _parse_breakdown_cohorts(list(cohorts), filter.hogql_context)
    ids = [cohort.pk for cohort in cohorts]
    if isinstance(filter.breakdown, list) and "all" in filter.breakdown:
        all_query, all_params = _format_all_query(team, filter, entity=entity)
        cohort_queries.append(all_query)
        params = {**params, **all_params}
        ids.append(ALL_USERS_COHORT_ID)
    return " UNION ALL ".join(cohort_queries), ids, params


def _parse_breakdown_cohorts(cohorts: list[Cohort], hogql_context: HogQLContext) -> tuple[list[str], dict]:
    queries = []
    params: dict[str, Any] = {}

    for idx, cohort in enumerate(cohorts):
        person_id_query, cohort_filter_params = format_filter_query(cohort, idx, hogql_context)
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
