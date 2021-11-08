from typing import Any, Dict, Tuple

from ee.clickhouse.models.action import format_action_filter
from ee.clickhouse.models.group import get_aggregation_target_field
from ee.clickhouse.queries.event_query import ClickhouseEventQuery
from ee.clickhouse.queries.util import get_trunc_func_ch
from posthog.constants import (
    PAGEVIEW_EVENT,
    TREND_FILTER_TYPE_ACTIONS,
    TREND_FILTER_TYPE_EVENTS,
    TRENDS_LINEAR,
    RetentionQueryType,
)
from posthog.models import Entity
from posthog.models.action import Action
from posthog.models.filters.retention_filter import RetentionFilter


class RetentionEventsQuery(ClickhouseEventQuery):
    _filter: RetentionFilter
    _event_query_type: RetentionQueryType
    _trunc_func: str

    def __init__(self, event_query_type: RetentionQueryType, *args, **kwargs):
        self._event_query_type = event_query_type
        super().__init__(*args, **kwargs)

        self._trunc_func = get_trunc_func_ch(self._filter.period)

    def get_query(self) -> Tuple[str, Dict[str, Any]]:
        _fields = [
            self.get_timestamp_field(),
            f"{get_aggregation_target_field(self._filter.aggregation_group_type_index, self.EVENT_TABLE_ALIAS, self.DISTINCT_ID_TABLE_ALIAS)} as target",
            (
                f"argMin(e.uuid, {self._trunc_func}(e.timestamp)) as min_uuid"
                if self._event_query_type == RetentionQueryType.TARGET_FIRST_TIME
                else f"{self.EVENT_TABLE_ALIAS}.uuid AS uuid"
            ),
            (
                f"argMin(e.event, {self._trunc_func}(e.timestamp)) as min_event"
                if self._event_query_type == RetentionQueryType.TARGET_FIRST_TIME
                else f"{self.EVENT_TABLE_ALIAS}.event AS event"
            ),
        ]
        _fields = list(filter(None, _fields))

        date_query, date_params = self._get_date_filter()
        self.params.update(date_params)

        prop_filters = [*self._filter.properties]
        prop_query, prop_params = self._get_props(prop_filters)
        self.params.update(prop_params)

        entity_query, entity_params = self._get_entity_query(
            entity=self._filter.target_entity
            if self._event_query_type == RetentionQueryType.TARGET
            or self._event_query_type == RetentionQueryType.TARGET_FIRST_TIME
            else self._filter.returning_entity
        )
        self.params.update(entity_params)

        person_query, person_params = self._get_person_query()
        self.params.update(person_params)

        groups_query, groups_params = self._get_groups_query()
        self.params.update(groups_params)

        query = f"""
            SELECT {','.join(_fields)} FROM events {self.EVENT_TABLE_ALIAS}
            {self._get_disintct_id_query()}
            {person_query}
            {groups_query}
            WHERE team_id = %(team_id)s
            {f"AND {entity_query}"}
            {f"AND {date_query}" if self._event_query_type != RetentionQueryType.TARGET_FIRST_TIME else ''}
            {prop_query}
            {f"GROUP BY target HAVING {date_query}" if self._event_query_type == RetentionQueryType.TARGET_FIRST_TIME else ''}
        """

        return query, self.params

    def get_timestamp_field(self) -> str:
        if self._event_query_type == RetentionQueryType.TARGET:
            return f"DISTINCT {self._trunc_func}({self.EVENT_TABLE_ALIAS}.timestamp) AS event_date"
        elif self._event_query_type == RetentionQueryType.TARGET_FIRST_TIME:
            return f"min({self._trunc_func}(e.timestamp)) as event_date"
        else:
            return f"{self.EVENT_TABLE_ALIAS}.timestamp AS event_date"

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
        return condition, params

    def _get_date_filter(self):
        query = (
            f"event_date >= toDateTime(%({self._event_query_type}_start_date)s) AND event_date <= toDateTime(%({self._event_query_type}_end_date)s)"
            if self._event_query_type == RetentionQueryType.TARGET_FIRST_TIME
            else f"toDateTime({self.EVENT_TABLE_ALIAS}.timestamp) >= toDateTime(%({self._event_query_type}_start_date)s) AND toDateTime({self.EVENT_TABLE_ALIAS}.timestamp) <= toDateTime(%({self._event_query_type}_end_date)s)"
        )
        params = {
            f"{self._event_query_type}_start_date": self._filter.date_from.strftime(
                "%Y-%m-%d{}".format(" %H:%M:%S" if self._filter.period == "Hour" else " 00:00:00")
            ),
            f"{self._event_query_type}_end_date": (
                (self._filter.date_from + self._filter.period_increment)
                if self._filter.display == TRENDS_LINEAR and self._event_query_type == RetentionQueryType.TARGET
                else self._filter.date_to
            ).strftime("%Y-%m-%d{}".format(" %H:%M:%S" if self._filter.period == "Hour" else " 00:00:00")),
        }
        return query, params
