from typing import Any, Dict, Tuple

from ee.clickhouse.models.group import get_aggregation_target_field
from ee.clickhouse.models.property import get_property_string_expr
from ee.clickhouse.queries.event_query import EnterpriseEventQuery
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.filters.filter import Filter


class FunnelEventQuery(EnterpriseEventQuery):
    _filter: Filter

    def get_query(self, entities=None, entity_name="events", skip_entity_filter=False) -> Tuple[str, Dict[str, Any]]:
        _fields = [
            f"{self.EVENT_TABLE_ALIAS}.event as event",
            f"{self.EVENT_TABLE_ALIAS}.team_id as team_id",
            f"{self.EVENT_TABLE_ALIAS}.distinct_id as distinct_id",
            f"{self.EVENT_TABLE_ALIAS}.timestamp as timestamp",
            (
                f"{self.EVENT_TABLE_ALIAS}.elements_chain as elements_chain"
                if self._column_optimizer.should_query_elements_chain_column
                else ""
            ),
            "{} as aggregation_target".format(
                get_aggregation_target_field(
                    self._filter.aggregation_group_type_index,
                    self.EVENT_TABLE_ALIAS,
                    f"{self.EVENT_TABLE_ALIAS}.distinct_id"
                    if self._aggregate_users_by_distinct_id
                    else f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id",
                )
            ),
        ]

        _fields += [f"{self.EVENT_TABLE_ALIAS}.{field} AS {field}" for field in self._extra_fields]
        _fields += [
            get_property_string_expr("events", field, f"'{field}'", "properties", table_alias=self.EVENT_TABLE_ALIAS)[0]
            + f' as "{field}"'
            for field in self._extra_event_properties
        ]

        _fields.extend(
            f'{self.EVENT_TABLE_ALIAS}."{column_name}" as "{column_name}"'
            for column_name in self._column_optimizer.event_columns_to_query
        )

        _fields.extend(
            f"groups_{group_index}.group_properties_{group_index} as group_properties_{group_index}"
            for group_index in self._column_optimizer.group_types_to_query
        )

        if self._should_join_persons:
            _fields.extend(
                f"{self.PERSON_TABLE_ALIAS}.{column_name} as {column_name}" for column_name in self._person_query.fields
            )

        _fields = list(filter(None, _fields))

        date_query, date_params = self._get_date_filter()
        self.params.update(date_params)

        prop_query, prop_params = self._get_prop_groups(self._filter.property_groups)

        self.params.update(prop_params)

        if skip_entity_filter:
            entity_query = ""
            entity_params: Dict[str, Any] = {}
        else:
            entity_query, entity_params = self._get_entity_query(entities, entity_name)

        self.params.update(entity_params)

        person_query, person_params = self._get_person_query()
        self.params.update(person_params)

        groups_query, groups_params = self._get_groups_query()
        self.params.update(groups_params)

        query = f"""
            SELECT {', '.join(_fields)} FROM events {self.EVENT_TABLE_ALIAS}
            {self._get_distinct_id_query()}
            {person_query}
            {groups_query}
            WHERE team_id = %(team_id)s
            {entity_query}
            {date_query}
            {prop_query}
        """

        return query, self.params

    def _determine_should_join_distinct_ids(self) -> None:
        if self._filter.aggregation_group_type_index is not None or self._aggregate_users_by_distinct_id:
            self._should_join_distinct_ids = False
        else:
            self._should_join_distinct_ids = True

    def _get_entity_query(self, entities=None, entity_name="events") -> Tuple[str, Dict[str, Any]]:
        events = set()
        entities_to_use = entities or self._filter.entities

        for entity in entities_to_use:
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                action = entity.get_action()
                for action_step in action.steps.all():
                    events.add(action_step.event)
            else:
                events.add(entity.id)

        return f"AND event IN %({entity_name})s", {entity_name: sorted(list(events))}
