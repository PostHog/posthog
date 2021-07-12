from typing import Any, Dict, List, Tuple

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.trends.util import populate_entity_params
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.person import GET_LATEST_PERSON_DISTINCT_ID_SQL, GET_LATEST_PERSON_SQL
from ee.clickhouse.sql.trends.top_elements import TOP_ELEMENTS_ARRAY_OF_KEY_SQL
from ee.clickhouse.sql.trends.top_person_props import TOP_PERSON_PROPS_ARRAY_OF_KEY_SQL
from posthog.models.entity import Entity
from posthog.models.filters.filter import Filter

# DEPRECATED (still used by Trends)


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
        latest_distinct_id_sql=GET_LATEST_PERSON_DISTINCT_ID_SQL,
        **entity_format_params
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
        **entity_format_params
    )
    top_elements_array = _get_top_elements(
        filter=filter,
        team_id=team_id,
        query=elements_query,
        params={**prop_filter_params, **entity_params},
        limit=limit,
    )

    return top_elements_array


# NEW (used by Funnels)

BREAKDOWN_LIMIT = 21  # 1 more than 20 to check if there's more than 20

QueryWithParams = Tuple[str, Dict[str, Any]]


def get_breakdown_person_prop_query(
    filter: Filter, entity: Entity, aggregate_operation: str, team_id: int, limit: int = 25
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

    elements_query = """
        SELECT prop FROM (
            SELECT prop, {aggregate_operation} AS count
            FROM events e 
            INNER JOIN (
                SELECT person_id, distinct_id FROM ({latest_distinct_id_sql}) WHERE team_id = %(team_id)s
            ) pdi
            ON e.distinct_id = pdi.distinct_id
            INNER JOIN (
                SELECT * FROM (
                    SELECT
                    id,
                    array_property_keys AS key,
                    array_property_values AS prop
                    from (
                        SELECT
                            id,
                            arrayMap(k -> toString(k.1), JSONExtractKeysAndValuesRaw(properties)) AS array_property_keys,
                            arrayMap(k -> toString(k.2), JSONExtractKeysAndValuesRaw(properties)) AS array_property_values
                        FROM ({latest_person_sql}) person WHERE team_id = %(team_id)s {person_prop_filters}
                    )
                    ARRAY JOIN array_property_keys, array_property_values
                ) ep
                WHERE key = %(breakdown_key)s
            ) ep
            ON person_id = ep.id
            WHERE
                e.team_id = %(team_id)s {entity_query} {parsed_date_from} {parsed_date_to} {prop_filters}
            GROUP BY prop
            ORDER BY count DESC
            LIMIT %(breakdown_limit)s OFFSET %(breakdown_offset)s
        )
    """.format(
        parsed_date_from=parsed_date_from,
        parsed_date_to=parsed_date_to,
        latest_person_sql=GET_LATEST_PERSON_SQL.format(query=""),
        prop_filters=prop_filters,
        person_prop_filters=person_prop_filters,
        aggregate_operation=aggregate_operation,
        latest_distinct_id_sql=GET_LATEST_PERSON_DISTINCT_ID_SQL,
        **entity_format_params
    )
    breakdown_params = {
        **prop_filter_params,
        **person_prop_params,
        **entity_params,
        "breakdown_key": filter.breakdown,
        "breakdown_limit": BREAKDOWN_LIMIT,
        "breakdown_offset": filter.offset,
    }

    return elements_query, breakdown_params


def get_breakdown_event_prop_query(
    filter: Filter, entity: Entity, aggregate_operation: str, team_id: int, limit: int = 25
) -> QueryWithParams:
    parsed_date_from, parsed_date_to, _ = parse_timestamps(filter=filter, team_id=team_id)
    prop_filters, prop_filter_params = parse_prop_clauses(
        filter.properties, team_id, table_name="e", filter_test_accounts=filter.filter_test_accounts,
    )

    entity_params, entity_format_params = populate_entity_params(entity)

    elements_query = """
        SELECT prop FROM (
            SELECT
                JSONExtractRaw(properties, %(breakdown_key)s) AS prop,
                {aggregate_operation} AS count
            FROM events e
            WHERE
                team_id = %(team_id)s {entity_query} {parsed_date_from} {parsed_date_to} {prop_filters}
            AND JSONHas(properties, %(breakdown_key)s)
            GROUP BY prop
            ORDER BY count DESC
            LIMIT %(breakdown_limit)s OFFSET %(breakdown_offset)s
        )
    """.format(
        parsed_date_from=parsed_date_from,
        parsed_date_to=parsed_date_to,
        prop_filters=prop_filters,
        aggregate_operation=aggregate_operation,
        **entity_format_params
    )
    breakdown_params = {
        **prop_filter_params,
        **entity_params,
        "breakdown_key": filter.breakdown,
        "breakdown_limit": BREAKDOWN_LIMIT,
        "breakdown_offset": filter.offset,
    }
    return elements_query, breakdown_params
