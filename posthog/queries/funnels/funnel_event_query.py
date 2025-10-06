from typing import Any, Union

from posthog.schema import PersonsOnEventsMode

from posthog.hogql.hogql import translate_hogql

from posthog.constants import TREND_FILTER_TYPE_ACTIONS
from posthog.models.filters.filter import Filter
from posthog.models.group.util import get_aggregation_target_field
from posthog.queries.event_query import EventQuery
from posthog.queries.util import get_person_properties_mode


class FunnelEventQuery(EventQuery):
    _filter: Filter

    def get_query(
        self,
        entities=None,
        entity_name="events",
        skip_entity_filter=False,
    ) -> tuple[str, dict[str, Any]]:
        # Aggregating by group
        if self._filter.aggregation_group_type_index is not None:
            aggregation_target = get_aggregation_target_field(
                self._filter.aggregation_group_type_index,
                self.EVENT_TABLE_ALIAS,
                self._person_id_alias,
            )

        # Aggregating by HogQL
        elif self._filter.funnel_aggregate_by_hogql and self._filter.funnel_aggregate_by_hogql != "person_id":
            aggregation_target = translate_hogql(
                self._filter.funnel_aggregate_by_hogql,
                events_table_alias=self.EVENT_TABLE_ALIAS,
                context=self._filter.hogql_context,
            )

        # Aggregating by Distinct ID
        elif self._aggregate_users_by_distinct_id:
            aggregation_target = f"{self.EVENT_TABLE_ALIAS}.distinct_id"

        # Aggregating by Person ID
        else:
            aggregation_target = self._person_id_alias

        _fields = [
            f"{self.EVENT_TABLE_ALIAS}.timestamp as timestamp",
            f"{aggregation_target} as aggregation_target",
        ]

        _fields += [f"{self.EVENT_TABLE_ALIAS}.{field} AS {field}" for field in self._extra_fields]

        if self._person_on_events_mode != PersonsOnEventsMode.DISABLED:
            _fields += [f"{self._person_id_alias} as person_id"]

            _fields.extend(
                f'{self.EVENT_TABLE_ALIAS}."{column_name}" as "{column_name}"'
                for column_name in sorted(self._column_optimizer.person_on_event_columns_to_query)
            )

        else:
            if self._should_join_distinct_ids:
                _fields += [f"{self._person_id_alias} as person_id"]
            if self._should_join_persons:
                _fields.extend(
                    f"{self.PERSON_TABLE_ALIAS}.{column_name} as {column_name}"
                    for column_name in sorted(self._person_query.fields)
                )

        _fields = list(filter(None, _fields))

        date_query, date_params = self._get_date_filter()
        self.params.update(date_params)

        prop_query, prop_params = self._get_prop_groups(
            self._filter.property_groups,
            person_properties_mode=get_person_properties_mode(self._team),
            person_id_joined_alias=self._person_id_alias,
        )

        self.params.update(prop_params)

        if skip_entity_filter:
            entity_query = ""
            entity_params: dict[str, Any] = {}
        else:
            entity_query, entity_params = self._get_entity_query(entities, entity_name)

        self.params.update(entity_params)

        person_query, person_params = self._get_person_query()
        self.params.update(person_params)

        groups_query, groups_params = self._get_groups_query()
        self.params.update(groups_params)

        null_person_filter = (
            f"AND notEmpty({self.EVENT_TABLE_ALIAS}.person_id)"
            if self._person_on_events_mode != PersonsOnEventsMode.DISABLED
            else ""
        )

        sample_clause = "SAMPLE %(sampling_factor)s" if self._filter.sampling_factor else ""
        self.params.update({"sampling_factor": self._filter.sampling_factor})

        all_fields = f"{', '.join(_fields)} {{extra_select_fields}}"

        # KLUDGE: Ideally we wouldn't mix string variables with f-string interpolation
        # but due to ordering requirements in functions building this query we do
        # things like this for now but should do a larger refactor to get rid of it
        query = f"""
            SELECT {all_fields}
            FROM events {self.EVENT_TABLE_ALIAS}
            {sample_clause}
            {self._get_person_ids_query(relevant_events_conditions=f"{entity_query} {date_query}")}
            {person_query}
            {groups_query}
            {{extra_join}}
            WHERE team_id = %(team_id)s
            {entity_query}
            {date_query}
            {prop_query}
            {null_person_filter}
            {{step_filter}}
        """

        return query, self.params

    def _determine_should_join_distinct_ids(self) -> None:
        non_person_id_aggregation = (
            self._filter.aggregation_group_type_index is not None or self._aggregate_users_by_distinct_id
        )
        is_using_cohort_propertes = self._column_optimizer.is_using_cohort_propertes

        if self._person_on_events_mode == PersonsOnEventsMode.PERSON_ID_OVERRIDE_PROPERTIES_ON_EVENTS:
            self._should_join_distinct_ids = True
        elif self._person_on_events_mode == PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS or (
            non_person_id_aggregation and not is_using_cohort_propertes
        ):
            self._should_join_distinct_ids = False
        else:
            self._should_join_distinct_ids = True

    def _determine_should_join_persons(self) -> None:
        EventQuery._determine_should_join_persons(self)
        if self._person_on_events_mode != PersonsOnEventsMode.DISABLED:
            self._should_join_persons = False

    def _get_entity_query(self, entities=None, entity_name="events") -> tuple[str, dict[str, Any]]:
        events: set[Union[int, str, None]] = set()
        entities_to_use = entities or self._filter.entities

        for entity in entities_to_use:
            if entity.type == TREND_FILTER_TYPE_ACTIONS:
                action = entity.get_action()
                events.update(action.get_step_events())
            else:
                events.add(entity.id)

        # If selecting for "All events", disable entity pre-filtering
        if None in events:
            return "AND 1 = 1", {}

        return f"AND event IN %({entity_name})s", {entity_name: sorted([x for x in events if x])}
