from typing import Any, Dict, Tuple

from ee.clickhouse.queries.event_query import ClickhouseEventQuery
from posthog.constants import TREND_FILTER_TYPE_ACTIONS


class FunnelEventQuery(ClickhouseEventQuery):
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
            f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id as person_id" if self._should_join_distinct_ids else "",
        ]

        _fields.extend(
            f"{self.EVENT_TABLE_ALIAS}.{column_name} as {column_name}"
            for column_name in self._column_optimizer.event_columns_to_query
        )

        if self._should_join_persons:
            _fields.extend(
                f"{self.PERSON_TABLE_ALIAS}.{column_name} as {column_name}" for column_name in self._person_query.fields
            )

        _fields = list(filter(None, _fields))

        date_query, date_params = self._get_date_filter()
        self.params.update(date_params)

        prop_filters = self._filter.properties
        prop_query, prop_params = self._get_props(prop_filters)
        self.params.update(prop_params)

        if skip_entity_filter:
            entity_query = ""
            entity_params: Dict[str, Any] = {}
        else:
            entity_query, entity_params = self._get_entity_query(entities, entity_name)

        self.params.update(entity_params)

        person_query, person_params = self._get_person_query()
        self.params.update(person_params)

        query = f"""
            SELECT {', '.join(_fields)} FROM events {self.EVENT_TABLE_ALIAS}
            {self._get_disintct_id_query()}
            {person_query}
            WHERE team_id = %(team_id)s
            {entity_query}
            {date_query}
            {prop_query}
        """

        return query, self.params

    def _determine_should_join_distinct_ids(self) -> None:
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

        return f"AND event IN %({entity_name})s", {entity_name: list(events)}
