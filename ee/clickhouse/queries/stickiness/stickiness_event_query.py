from typing import Any, Dict, Tuple

from ee.clickhouse.models.group import get_aggregation_target_field
from posthog.constants import TREND_FILTER_TYPE_ACTIONS, PropertyOperatorType
from posthog.models import Entity
from posthog.models.action.util import format_action_filter
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.models.utils import PersonPropertiesMode
from posthog.queries.event_query import EventQuery
from posthog.queries.util import get_trunc_func_ch


class StickinessEventsQuery(EventQuery):
    _entity: Entity
    _filter: StickinessFilter

    def __init__(self, entity: Entity, *args, **kwargs):
        self._entity = entity
        super().__init__(*args, **kwargs)

    def get_query(self) -> Tuple[str, Dict[str, Any]]:

        prop_query, prop_params = self._get_prop_groups(
            self._filter.property_groups.combine_property_group(PropertyOperatorType.AND, self._entity.property_groups),
            person_properties_mode=PersonPropertiesMode.DIRECT_ON_EVENTS
            if self._using_person_on_events
            else PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
            person_id_joined_alias=f"{self.DISTINCT_ID_TABLE_ALIAS if not self._using_person_on_events else self.EVENT_TABLE_ALIAS}.person_id",
        )

        self.params.update(prop_params)

        actions_query, actions_params = self.get_actions_query()
        self.params.update(actions_params)

        date_query, date_params = self._get_date_filter()
        self.params.update(date_params)

        person_query, person_params = self._get_person_query()
        self.params.update(person_params)

        groups_query, groups_params = self._get_groups_query()
        self.params.update(groups_params)

        query = f"""
            SELECT
                {self.aggregation_target()} AS aggregation_target,
                countDistinct({get_trunc_func_ch(self._filter.interval)}(toDateTime(timestamp, %(timezone)s))) as num_intervals
            FROM events {self.EVENT_TABLE_ALIAS}
            {self._get_distinct_id_query()}
            {person_query}
            {groups_query}
            WHERE team_id = %(team_id)s
              {date_query}
              AND {actions_query}
              {prop_query}
            GROUP BY aggregation_target
        """

        return query, self.params

    def _determine_should_join_distinct_ids(self) -> None:
        self._should_join_distinct_ids = True

    def _determine_should_join_persons(self) -> None:
        EventQuery._determine_should_join_persons(self)
        if self._using_person_on_events:
            self._should_join_distinct_ids = False
            self._should_join_persons = False

    def aggregation_target(self):
        return get_aggregation_target_field(
            self._entity.math_group_type_index,
            self.EVENT_TABLE_ALIAS,
            f"{self.DISTINCT_ID_TABLE_ALIAS if not self._using_person_on_events else self.EVENT_TABLE_ALIAS}.person_id",
        )

    def get_actions_query(self) -> Tuple[str, Dict[str, Any]]:
        if self._entity.type == TREND_FILTER_TYPE_ACTIONS:
            return format_action_filter(
                team_id=self._team_id,
                action=self._entity.get_action(),
                person_properties_mode=PersonPropertiesMode.DIRECT_ON_EVENTS
                if self._using_person_on_events
                else PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
                person_id_joined_alias=f"{self.DISTINCT_ID_TABLE_ALIAS if not self._using_person_on_events else self.EVENT_TABLE_ALIAS}.person_id",
            )
        else:
            return "event = %(event)s", {"event": self._entity.id}
