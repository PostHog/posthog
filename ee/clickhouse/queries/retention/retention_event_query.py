from typing import Any, Dict, Literal, Tuple

from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.queries.event_query import ClickhouseEventQuery
from posthog.constants import PAGEVIEW_EVENT, TREND_FILTER_TYPE_ACTIONS, TREND_FILTER_TYPE_EVENTS, TRENDS_LINEAR
from posthog.models import Entity
from posthog.models.action import Action
from posthog.models.filters.retention_filter import RetentionFilter


class RetentionEventsQuery(ClickhouseEventQuery):
    _filter: RetentionFilter
    _event_query_type: Literal["returning", "target"]

    def __init__(self, event_query_type: Literal["returning", "target"], *args, **kwargs):
        self._event_query_type = event_query_type
        super().__init__(*args, **kwargs)

    def get_query(self) -> Tuple[str, Dict[str, Any]]:
        _fields = (
            f"{self.EVENT_TABLE_ALIAS}.timestamp AS event_date"
            + (f", {self.DISTINCT_ID_TABLE_ALIAS}.person_id as person_id" if self._should_join_distinct_ids else "")
            + f", {self.EVENT_TABLE_ALIAS}.uuid AS uuid"
            + f", {self.EVENT_TABLE_ALIAS}.event AS event"
        )

        date_query, date_params = self._get_date_filter()
        self.params.update(date_params)

        prop_filters = [*self._filter.properties]
        prop_query, prop_params = self._get_props(prop_filters)
        self.params.update(prop_params)

        entity_query, entity_params = self._get_entity_query(
            entity=self._filter.target_entity if self._event_query_type == "target" else self._filter.returning_entity
        )
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

    def _get_entity_query(self, entity: Entity):
        prepend = self._event_query_type
        if entity.type == TREND_FILTER_TYPE_ACTIONS:
            action = Action.objects.get(pk=entity.id)
            action_query, params = format_action_filter(action, prepend=prepend, use_loop=False)
            condition = action_query
        elif entity.type == TREND_FILTER_TYPE_EVENTS:
            condition = f"{self.EVENT_TABLE_ALIAS}.event = %({prepend}_event)s"
            params = {f"{prepend}_event": entity.id}
        else:
            condition = f"{self.EVENT_TABLE_ALIAS}.event = %({prepend}_event)s"
            params = {f"{prepend}_event": PAGEVIEW_EVENT}
        return f"AND {condition}", params

    def _get_date_filter(self):
        query = f"toDateTime({self.EVENT_TABLE_ALIAS}.timestamp) >= toDateTime(%({self._event_query_type}_start_date)s) AND toDateTime({self.EVENT_TABLE_ALIAS}.timestamp) <= toDateTime(%({self._event_query_type}_end_date)s)"
        params = {
            f"{self._event_query_type}_start_date": self._filter.date_from.strftime(
                "%Y-%m-%d{}".format(" %H:%M:%S" if self._filter.period == "Hour" else " 00:00:00")
            ),
            f"{self._event_query_type}_end_date": (
                (self._filter.date_from + self._filter.period_increment)
                if self._filter.display == TRENDS_LINEAR
                else self._filter.date_to
            ).strftime("%Y-%m-%d{}".format(" %H:%M:%S" if self._filter.period == "Hour" else " 00:00:00")),
        }
        return f"AND {query}", params
