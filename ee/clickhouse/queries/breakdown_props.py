from typing import Dict, List

from ee.clickhouse.client import sync_execute
from ee.clickhouse.models.property import parse_prop_clauses
from ee.clickhouse.queries.trends.util import populate_entity_params
from ee.clickhouse.queries.util import parse_timestamps
from ee.clickhouse.sql.person import GET_LATEST_PERSON_DISTINCT_ID_SQL, GET_LATEST_PERSON_SQL
from ee.clickhouse.sql.trends.top_elements import TOP_ELEMENTS_ARRAY_OF_KEY_SQL
from ee.clickhouse.sql.trends.top_person_props import TOP_PERSON_PROPS_ARRAY_OF_KEY_SQL
from posthog.models.entity import Entity
from posthog.models.filters.filter import Filter


class BreakdownProps:
    _filter: Filter
    _team_id: int
    _entity: Entity
    _aggregate_operation: str

    def __init__(self, filter: Filter, entity: Entity, aggregate_operation: str, team_id: int) -> None:
        self._filter = filter
        self._team_id = team_id
        self._entity = entity
        self._aggregate_operation = aggregate_operation

    def _get_top_elements(self, query: str, params: Dict = {}) -> List:
        # use limit of 25 to determine if there are more than 20
        element_params = {
            "key": self._filter.breakdown,
            "limit": 25,
            "team_id": self._team_id,
            "offset": self._filter.offset,
            **params,
        }

        try:
            top_elements_array_result = sync_execute(query, element_params)
            top_elements_array = top_elements_array_result[0][0]
        except:
            top_elements_array = []

        return top_elements_array

    def get_person_prop_params(self):
        parsed_date_from, parsed_date_to, _ = parse_timestamps(filter=self._filter, team_id=self._team_id)
        prop_filters, prop_filter_params = parse_prop_clauses(
            self._filter.properties,
            self._team_id,
            table_name="e",
            filter_test_accounts=self._filter.filter_test_accounts,
        )
        person_prop_filters, person_prop_params = parse_prop_clauses(
            [prop for prop in self._filter.properties if prop.type == "person"],
            self._team_id,
            table_name="e",
            filter_test_accounts=self._filter.filter_test_accounts,
            is_person_query=True,
        )

        entity_params, entity_format_params = populate_entity_params(self._entity)

        elements_query = TOP_PERSON_PROPS_ARRAY_OF_KEY_SQL.format(
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            latest_person_sql=GET_LATEST_PERSON_SQL.format(query=""),
            prop_filters=prop_filters,
            person_prop_filters=person_prop_filters,
            aggregate_operation=self._aggregate_operation,
            latest_distinct_id_sql=GET_LATEST_PERSON_DISTINCT_ID_SQL,
            **entity_format_params
        )
        top_elements_array = self._get_top_elements(
            elements_query,
            self._filter,
            self._team_id,
            params={**prop_filter_params, **person_prop_params, **entity_params},
        )

        return top_elements_array

    def get_event_prop_values(self):
        parsed_date_from, parsed_date_to, _ = parse_timestamps(filter=self._filter, team_id=self._team_id)
        prop_filters, prop_filter_params = parse_prop_clauses(
            self._filter.properties,
            self._team_id,
            table_name="e",
            filter_test_accounts=self._filter.filter_test_accounts,
        )

        entity_params, entity_format_params = populate_entity_params(self._entity)

        elements_query = TOP_ELEMENTS_ARRAY_OF_KEY_SQL.format(
            parsed_date_from=parsed_date_from,
            parsed_date_to=parsed_date_to,
            prop_filters=prop_filters,
            aggregate_operation=self._aggregate_operation,
            **entity_format_params
        )
        top_elements_array = self._get_top_elements(
            elements_query, self._filter, self._team_id, params={**prop_filter_params, **entity_params}
        )

        return top_elements_array
