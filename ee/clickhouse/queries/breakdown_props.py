from typing import Any, Dict, List, Tuple

from django.db.models.manager import BaseManager

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.cohort import format_filter_query
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.trends.util import populate_entity_params
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.person import GET_LATEST_PERSON_SQL, GET_TEAM_PERSON_DISTINCT_IDS
from ee.clickhouse.sql.trends.top_elements import TOP_ELEMENTS_ARRAY_OF_KEY_SQL
from ee.clickhouse.sql.trends.top_person_props import TOP_PERSON_PROPS_ARRAY_OF_KEY_SQL
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters.filter import Filter


def _get_top_elements(filter: Filter, team_id: int, query: str, limit, params: Dict = {}) -> List:
    # use limit of 25 to determine if there are more than 20
    element_params = {
        "key": filter.breakdown,
        "limit": limit,
        "team_id": team_id,
        "offset": filter.offset,
        **params,
    }

    try:
        top_elements_array_result = sync_execute(query, element_params)
        top_elements_array = top_elements_array_result[0][0]
    except:
        top_elements_array = []

    return top_elements_array


def get_breakdown_person_prop_values(
    filter: Filter, entity: Entity, aggregate_operation: str, team_id: int, limit: int = 25
):
    parsed_date_from, parsed_date_to, _ = parse_timestamps(filter=filter, team_id=team_id)
    prop_filters, prop_filter_params = parse_prop_clauses(
        filter.properties, team_id, table_name="e", filter_test_accounts=filter.filter_test_accounts,
    )
    person_prop_filters, person_prop_params = parse_prop_clauses(
        [prop for prop in filter.properties if prop.type == "person"],
        team_id,
        table_name="e",
        filter_test_accounts=filter.filter_test_accounts,
        is_person_query=True,
    )

    entity_params, entity_format_params = populate_entity_params(entity)

    elements_query = TOP_PERSON_PROPS_ARRAY_OF_KEY_SQL.format(
        parsed_date_from=parsed_date_from,
        parsed_date_to=parsed_date_to,
        latest_person_sql=GET_LATEST_PERSON_SQL.format(query=""),
        prop_filters=prop_filters,
        person_prop_filters=person_prop_filters,
        aggregate_operation=aggregate_operation,
        GET_TEAM_PERSON_DISTINCT_IDS=GET_TEAM_PERSON_DISTINCT_IDS,
        **entity_format_params,
    )
    top_elements_array = _get_top_elements(
        filter=filter,
        team_id=team_id,
        query=elements_query,
        params={**prop_filter_params, **person_prop_params, **entity_params},
        limit=limit,
    )

    return top_elements_array


def get_breakdown_event_prop_values(
    filter: Filter, entity: Entity, aggregate_operation: str, team_id: int, limit: int = 25
):
    parsed_date_from, parsed_date_to, _ = parse_timestamps(filter=filter, team_id=team_id)
    prop_filters, prop_filter_params = parse_prop_clauses(
        filter.properties, team_id, table_name="e", filter_test_accounts=filter.filter_test_accounts,
    )

    entity_params, entity_format_params = populate_entity_params(entity)

    elements_query = TOP_ELEMENTS_ARRAY_OF_KEY_SQL.format(
        parsed_date_from=parsed_date_from,
        parsed_date_to=parsed_date_to,
        prop_filters=prop_filters,
        aggregate_operation=aggregate_operation,
        **entity_format_params,
    )
    top_elements_array = _get_top_elements(
        filter=filter,
        team_id=team_id,
        query=elements_query,
        params={**prop_filter_params, **entity_params},
        limit=limit,
    )

    return top_elements_array


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
            SELECT DISTINCT distinct_id, 0 as value
            FROM events all_events
            WHERE team_id = {team_id} 
            {parsed_date_from} 
            {parsed_date_to} 
            {prop_filters}
            """
    return query, {**date_params, **prop_filter_params}


def format_breakdown_cohort_join_query(team_id: int, filter: Filter, **kwargs) -> Tuple[str, List, Dict]:
    entity = kwargs.pop("entity", None)
    cohorts = Cohort.objects.filter(team_id=team_id, pk__in=[b for b in filter.breakdown if b != "all"])
    cohort_queries, params = _parse_breakdown_cohorts(cohorts)
    ids = [cohort.pk for cohort in cohorts]
    if "all" in filter.breakdown:
        all_query, all_params = _format_all_query(team_id, filter, entity=entity)
        cohort_queries.append(all_query)
        params = {**params, **all_params}
        ids.append(0)
    return " UNION ALL ".join(cohort_queries), ids, params


def _parse_breakdown_cohorts(cohorts: BaseManager) -> Tuple[List[str], Dict]:
    queries = []
    params: Dict[str, Any] = {}
    for idx, cohort in enumerate(cohorts):
        person_id_query, cohort_filter_params = format_filter_query(cohort, idx)
        params = {**params, **cohort_filter_params}
        cohort_query = person_id_query.replace("SELECT distinct_id", f"SELECT distinct_id, {cohort.pk} as value")
        queries.append(cohort_query)
    return queries, params
