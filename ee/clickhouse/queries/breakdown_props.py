from typing import Any, Dict, List, Tuple

from django.db.models.manager import BaseManager

from ee.clickhouse.models.cohort import format_filter_query
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.trends.util import populate_entity_params
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.person import GET_LATEST_PERSON_SQL, GET_TEAM_PERSON_DISTINCT_IDS
from posthog.models.cohort import Cohort
from posthog.models.entity import Entity
from posthog.models.filters.filter import Filter

QueryWithParams = Tuple[str, Dict[str, Any]]


def get_breakdown_person_prop_query(
    filter: Filter,
    entity: Entity,
    aggregate_operation: str,
    team_id: int,
    limit: int = 25,
    *,
    include_none: bool = False,
) -> QueryWithParams:
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

    elements_query = f"""
        SELECT breakdown_value FROM (
            SELECT breakdown_value, {aggregate_operation} AS count
            FROM events e 
            INNER JOIN (SELECT person_id, distinct_id FROM ({GET_TEAM_PERSON_DISTINCT_IDS})) AS pdi ON e.distinct_id = pdi.distinct_id
            INNER JOIN
                (
                    SELECT * FROM (
                        SELECT id, array_property_keys AS key, array_property_values AS breakdown_value
                        FROM (
                            SELECT
                                id,
                                arrayMap(k -> toString(k.1), JSONExtractKeysAndValuesRaw(properties)) AS array_property_keys,
                                arrayMap(k -> trim(BOTH '\"' FROM k.2), JSONExtractKeysAndValuesRaw(properties)) AS array_property_values
                            FROM ({GET_LATEST_PERSON_SQL.format(query="")}) person WHERE team_id = %(team_id)s {person_prop_filters}
                        )
                        ARRAY JOIN array_property_keys, array_property_values
                    ) ep
                    WHERE key = %(key)s
                ) ep ON person_id = ep.id
            WHERE
                e.team_id = %(team_id)s {entity_format_params["entity_query"]} {parsed_date_from} {parsed_date_to} {prop_filters}
            GROUP BY breakdown_value
            ORDER BY count DESC
            LIMIT %(breakdown_limit)s OFFSET %(breakdown_offset)s
        )"""

    if include_none:
        elements_query += " UNION ALL ( SELECT 'none')"

    return (
        elements_query,
        {**entity_params, "key": filter.breakdown, "breakdown_limit": limit, "breakdown_offset": filter.offset,},
    )


def get_breakdown_event_prop_query(
    filter: Filter,
    entity: Entity,
    aggregate_operation: str,
    team_id: int,
    limit: int = 25,
    *,
    include_none: bool = False,
) -> QueryWithParams:
    parsed_date_from, parsed_date_to, _ = parse_timestamps(filter=filter, team_id=team_id)
    prop_filters, prop_filter_params = parse_prop_clauses(
        filter.properties, team_id, table_name="e", filter_test_accounts=filter.filter_test_accounts,
    )
    entity_params, entity_format_params = populate_entity_params(entity)

    elements_query = f"""
        SELECT breakdown_value FROM (
            SELECT
                trim(BOTH '\"' FROM JSONExtractRaw(properties, %(key)s)) AS breakdown_value,
                {aggregate_operation} AS count
            FROM events e
            WHERE
                team_id = %(team_id)s {entity_format_params["entity_query"]} {parsed_date_from} {parsed_date_to} {prop_filters}
            AND JSONHas(properties, %(key)s)
            GROUP BY breakdown_value
            ORDER BY count DESC
            LIMIT %(breakdown_limit)s OFFSET %(breakdown_offset)s
        )"""

    if include_none:
        elements_query += " UNION ALL ( SELECT 'none')"

    return (
        elements_query,
        {**entity_params, "key": filter.breakdown, "breakdown_limit": limit, "breakdown_offset": filter.offset,},
    )


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
    cohorts = (
        Cohort.objects.filter(team_id=team_id, pk__in=[b for b in filter.breakdown if b != "all"])
        if isinstance(filter.breakdown, list)
        else Cohort.objects.filter(team_id=team_id, pk=filter.breakdown)
    )
    cohort_queries, params = _parse_breakdown_cohorts(cohorts)
    ids = [cohort.pk for cohort in cohorts]
    if isinstance(filter.breakdown, list) and "all" in filter.breakdown:
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
