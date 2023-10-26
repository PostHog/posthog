from typing import Any, Dict, Tuple

from posthog.constants import TREND_FILTER_TYPE_ACTIONS, PropertyOperatorType
from posthog.models import Entity
from posthog.models.action.util import format_action_filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.filters.stickiness_filter import StickinessFilter
from posthog.queries.event_query import EventQuery
from posthog.queries.person_query import PersonQuery
from posthog.queries.util import get_person_properties_mode, get_start_of_interval_sql
from posthog.utils import PersonOnEventsMode


class StickinessEventsQuery(EventQuery):
    _entity: Entity
    _filter: StickinessFilter

    def __init__(self, entity: Entity, *args, **kwargs):
        self._entity = entity
        super().__init__(*args, **kwargs)

    def get_query(self) -> Tuple[str, Dict[str, Any]]:
        prop_query, prop_params = self._get_prop_groups(
            self._filter.property_groups.combine_property_group(PropertyOperatorType.AND, self._entity.property_groups),
            person_properties_mode=get_person_properties_mode(self._team),
            person_id_joined_alias=self._person_id_alias,
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

        null_person_filter = (
            f"AND notEmpty({self.EVENT_TABLE_ALIAS}.person_id)"
            if self._person_on_events_mode != PersonOnEventsMode.DISABLED
            else ""
        )

        sample_clause = "SAMPLE %(sampling_factor)s" if self._filter.sampling_factor else ""
        self.params.update({"sampling_factor": self._filter.sampling_factor})

        query = f"""
            SELECT
                {self.aggregation_target()} AS aggregation_target,
                countDistinct(
                    {get_start_of_interval_sql(self._filter.interval, team=self._team)}
                ) as num_intervals
            FROM events {self.EVENT_TABLE_ALIAS}
            {sample_clause}
            {self._get_person_ids_query()}
            {person_query}
            {groups_query}
            WHERE team_id = %(team_id)s
            {date_query}
            AND {actions_query}
            {prop_query}
            {null_person_filter}
            GROUP BY aggregation_target
        """

        return query, self.params

    @cached_property
    def _person_query(self):
        return PersonQuery(
            self._filter,
            self._team_id,
            self._column_optimizer,
            extra_fields=self._extra_person_fields,
            entity=self._entity,
        )

    def _determine_should_join_distinct_ids(self) -> None:
        if self._person_on_events_mode == PersonOnEventsMode.V1_ENABLED:
            self._should_join_distinct_ids = False
        else:
            self._should_join_distinct_ids = True

    def _determine_should_join_persons(self) -> None:
        EventQuery._determine_should_join_persons(self)
        if self._person_on_events_mode != PersonOnEventsMode.DISABLED:
            self._should_join_persons = False

    def aggregation_target(self):
        return self._person_id_alias

    def get_actions_query(self) -> Tuple[str, Dict[str, Any]]:
        if self._entity.type == TREND_FILTER_TYPE_ACTIONS:
            return format_action_filter(
                team_id=self._team_id,
                action=self._entity.get_action(),
                person_properties_mode=get_person_properties_mode(self._team),
                person_id_joined_alias=f"{self.aggregation_target()}",
                hogql_context=self._filter.hogql_context,
            )
        elif self._entity.id is None:
            return "1 = 1", {}
        else:
            return "event = %(event)s", {"event": self._entity.id}
