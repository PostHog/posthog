from typing import Any, Dict, Tuple

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.filters.filter import Filter
from posthog.models.group.util import get_aggregation_target_field
from posthog.models.property.util import get_property_string_expr
from posthog.models.utils import PersonPropertiesMode
from posthog.queries.event_query import EventQuery


class FunnelEventQuery(EventQuery):
    _filter: Filter

    def get_query(self, entities=None, entity_name="events", skip_entity_filter=False) -> Tuple[str, Dict[str, Any]]:

        aggregation_target = (
            get_aggregation_target_field(
                self._filter.aggregation_group_type_index,
                self.EVENT_TABLE_ALIAS,
                f"{self.EVENT_TABLE_ALIAS}.person_id",
            )
            if self._using_person_on_events
            else get_aggregation_target_field(
                self._filter.aggregation_group_type_index,
                self.EVENT_TABLE_ALIAS,
                f"{self.EVENT_TABLE_ALIAS}.distinct_id"
                if self._aggregate_users_by_distinct_id
                else f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id",
            )
        )

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
            f"{aggregation_target} as aggregation_target",
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

        if self._using_person_on_events:
            _fields += [f"{self.EVENT_TABLE_ALIAS}.person_id as person_id"]
            _fields.extend(
                f"group{group_index}_properties AS group{group_index}_properties"
                for group_index in self._column_optimizer.group_types_to_query
            )

            if self._column_optimizer.person_columns_to_query:
                _fields += [f"{self.EVENT_TABLE_ALIAS}.person_properties AS person_properties"]
        else:
            if self._should_join_distinct_ids:
                _fields += [f"{self.DISTINCT_ID_TABLE_ALIAS}.person_id as person_id"]
            _fields.extend(
                f"groups_{group_index}.group_properties_{group_index} as group_properties_{group_index}"
                for group_index in self._column_optimizer.group_types_to_query
            )

            if self._should_join_persons:
                _fields.extend(
                    f"{self.PERSON_TABLE_ALIAS}.{column_name} as {column_name}"
                    for column_name in self._person_query.fields
                )

        if self._should_join_sessions:
            if "$session_id" not in self._extra_event_properties:
                _fields.append(f'{self.SESSION_TABLE_ALIAS}.$session_id as "$session_id"')
            _fields.append(f"{self.SESSION_TABLE_ALIAS}.session_duration as session_duration")

        _fields = list(filter(None, _fields))

        date_query, date_params = self._get_date_filter()
        self.params.update(date_params)

        prop_query, prop_params = self._get_prop_groups(
            self._filter.property_groups,
            person_properties_mode=PersonPropertiesMode.DIRECT_ON_EVENTS
            if self._using_person_on_events
            else PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
            person_id_joined_alias=f"{self.DISTINCT_ID_TABLE_ALIAS if not self._using_person_on_events else self.EVENT_TABLE_ALIAS}.person_id",
        )

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

        session_query, session_params = self._get_sessions_query()
        self.params.update(session_params)

        query = f"""
            SELECT {', '.join(_fields)} FROM events {self.EVENT_TABLE_ALIAS}
            {self._get_distinct_id_query()}
            {person_query}
            {groups_query}
            {session_query}
            WHERE team_id = %(team_id)s
            {entity_query}
            {date_query}
            {prop_query}
        """
        return query, self.params

    def _determine_should_join_distinct_ids(self) -> None:
        if (
            self._filter.aggregation_group_type_index is not None or self._aggregate_users_by_distinct_id
        ) and not self._column_optimizer.is_using_cohort_propertes:
            self._should_join_distinct_ids = False
        else:
            self._should_join_distinct_ids = True

    def _determine_should_join_persons(self) -> None:
        EventQuery._determine_should_join_persons(self)
        if self._using_person_on_events:
            self._should_join_distinct_ids = False
            self._should_join_persons = False

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
