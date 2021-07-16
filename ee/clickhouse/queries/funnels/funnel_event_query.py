from typing import Any, Dict, Tuple

from django.conf import settings

from ee.clickhouse.queries.event_query import ClickhouseEventQuery
from ee.settings import CLICKHOUSE_DENORMALIZED_PROPERTIES
from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.action import Action


class FunnelEventQuery(ClickhouseEventQuery):
    def get_query(self, entities=None, entity_name="events", skip_entity_filter=False) -> Tuple[str, Dict[str, Any]]:
        _fields = (
            f"{self.EVENT_TABLE_ALIAS}.event as event, {self.EVENT_TABLE_ALIAS}.team_id as team_id, {self.EVENT_TABLE_ALIAS}.distinct_id as distinct_id, {self.EVENT_TABLE_ALIAS}.timestamp as timestamp, {self.EVENT_TABLE_ALIAS}.properties as properties, {self.EVENT_TABLE_ALIAS}.elements_chain as elements_chain"
            + (f", {self.DISTINCT_ID_TABLE_ALIAS}.person_id as person_id" if self._should_join_distinct_ids else "")
            + (f", {self.PERSON_TABLE_ALIAS}.person_props as person_props" if self._should_join_persons else "")
            + (
                " ".join(
                    [
                        f", {self.EVENT_TABLE_ALIAS}.properties_{prop} as properties_{prop}"
                        for prop in settings.CLICKHOUSE_DENORMALIZED_PROPERTIES
                    ]
                )
            )
        )

        date_query, date_params = self._get_date_filter()
        self.params.update(date_params)

        prop_filters = self._filter.properties
        prop_query, prop_params = self._get_props(prop_filters, allow_denormalized_props=True)
        self.params.update(prop_params)

        if skip_entity_filter:
            entity_query = ""
            entity_params: Dict[str, Any] = {}
        else:
            entity_query, entity_params = self._get_entity_query(entities, entity_name)

        self.params.update(entity_params)

        query = f"""
            SELECT {_fields} FROM events {self.EVENT_TABLE_ALIAS}
            {self._get_disintct_id_query()}
            {self._get_person_query()}
            WHERE team_id = %(team_id)s
            {entity_query}
            {date_query}
            {prop_query}
        """

        return query, self.params

    def _determine_should_join_distinct_ids(self) -> None:
        self._should_join_distinct_ids = True

    def _get_entity_query(self, entities=None, entity_name="events") -> Tuple[str, Dict[str, Any]]:
        events = []
        entities_to_use = entities or self._filter.entities

        for entity in entities_to_use:
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                action = entity.get_action()
                for action_step in action.steps.all():
                    events.append(action_step.event)
            else:
                events.append(entity.id)

        return f"AND event IN %({entity_name})s", {entity_name: events}
