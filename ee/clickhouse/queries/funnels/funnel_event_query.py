from typing import Any, Dict, Tuple

from ee.clickhouse.queries.event_query import ClickhouseEventQuery
from ee.clickhouse.query_builder import SQL, SQLFragment
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

        _fields = SQL(", ".join(filter(None, _fields)))

        return SQL(
            """
            SELECT {_fields} FROM events {self.EVENT_TABLE_ALIAS!s}
            {self._get_disintct_id_query()}
            {self._get_person_query()}
            WHERE team_id = %(team_id)s
            {self._get_entity_query(entities, entity_name, skip=skip_entity_filter)}
            {self._get_date_filter()}
            {self._get_props(self._filter.properties)}
            """,
            {"team_id": self._team_id},
        )

    def _determine_should_join_distinct_ids(self) -> None:
        self._should_join_distinct_ids = True

    def _get_entity_query(self, entities=None, entity_name="events", skip: bool = False) -> SQLFragment:
        if skip:
            return SQL("")

        events = set()
        entities_to_use = entities or self._filter.entities

        for entity in entities_to_use:
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                action = entity.get_action()
                for action_step in action.steps.all():
                    events.add(action_step.event)
            else:
                events.add(entity.id)

        return SQL(f"AND event IN %({entity_name})s", {entity_name: list(events)})
