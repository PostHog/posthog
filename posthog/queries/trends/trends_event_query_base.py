from typing import Any, Dict, Tuple

from posthog.constants import MONTHLY_ACTIVE, UNIQUE_USERS, WEEKLY_ACTIVE, PropertyOperatorType
from posthog.models import Entity
from posthog.models.entity.util import get_entity_filtering_params
from posthog.models.filters.filter import Filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.models.utils import PersonPropertiesMode
from posthog.queries.event_query import EventQuery
from posthog.queries.person_query import PersonQuery
from posthog.queries.query_date_range import QueryDateRange
from posthog.queries.trends.util import get_active_user_params


class TrendsEventQueryBase(EventQuery):
    _entity: Entity
    _filter: Filter

    def __init__(self, entity: Entity, *args, **kwargs):
        self._entity = entity
        super().__init__(*args, **kwargs)

    def get_query_base(self) -> Tuple[str, Dict[str, Any]]:
        """
        Returns part of the event query with only FROM, JOINs and WHERE clauses.
        """

        date_query, date_params = self._get_date_filter()
        self.params.update(date_params)

        prop_query, prop_params = self._get_prop_groups(
            self._filter.property_groups.combine_property_group(PropertyOperatorType.AND, self._entity.property_groups),
            person_properties_mode=PersonPropertiesMode.DIRECT_ON_EVENTS
            if self._using_person_on_events
            else PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
            person_id_joined_alias=f"{self.DISTINCT_ID_TABLE_ALIAS if not self._using_person_on_events else self.EVENT_TABLE_ALIAS}.person_id",
        )

        self.params.update(prop_params)

        entity_query, entity_params = self._get_entity_query()
        self.params.update(entity_params)

        person_query, person_params = self._get_person_query()
        self.params.update(person_params)

        groups_query, groups_params = self._get_groups_query()
        self.params.update(groups_params)

        session_query, session_params = self._get_sessions_query()
        self.params.update(session_params)

        sample_clause = f"SAMPLE {self._filter.sampling_factor}" if self._filter.sampling_factor else ""

        query = f"""
            FROM events {self.EVENT_TABLE_ALIAS}
            {sample_clause}
            {self._get_distinct_id_query()}
            {person_query}
            {groups_query}
            {session_query}
            WHERE team_id = %(team_id)s
            {entity_query}
            {date_query}
            {prop_query}
            {self._get_not_null_actor_condition()}
        """

        return query, self.params

    def _determine_should_join_persons(self) -> None:
        if self._using_person_on_events:
            self._should_join_distinct_ids = False
            self._should_join_persons = False
        else:
            EventQuery._determine_should_join_persons(self)

    def _determine_should_join_distinct_ids(self) -> None:
        is_entity_per_user = self._entity.math in (UNIQUE_USERS, WEEKLY_ACTIVE, MONTHLY_ACTIVE)
        if (
            is_entity_per_user and not self._aggregate_users_by_distinct_id
        ) or self._column_optimizer.is_using_cohort_propertes:
            self._should_join_distinct_ids = True

    def _get_not_null_actor_condition(self) -> str:
        if self._entity.math_group_type_index is None:
            # If aggregating by person, exclude events with null/zero person IDs
            return f"AND notEmpty({self.EVENT_TABLE_ALIAS}.person_id)" if self._using_person_on_events else ""
        else:
            # If aggregating by group, exclude events that aren't associated with a group
            return f"""AND "$group_{self._entity.math_group_type_index}" != ''"""

    def _get_date_filter(self) -> Tuple[str, Dict]:
        date_filter = ""
        query_params: Dict[str, Any] = {}
        query_date_range = QueryDateRange(self._filter, self._team)
        parsed_date_from, date_from_params = query_date_range.date_from
        parsed_date_to, date_to_params = query_date_range.date_to

        query_params.update(date_from_params)
        query_params.update(date_to_params)

        self.parsed_date_from = parsed_date_from
        self.parsed_date_to = parsed_date_to

        if self._entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]:
            active_user_format_params, active_user_query_params = get_active_user_params(
                self._filter, self._entity, self._team_id
            )
            self.active_user_params = active_user_format_params
            query_params.update(active_user_query_params)

            date_filter = "{parsed_date_from_prev_range} {parsed_date_to}".format(
                **active_user_format_params, parsed_date_to=parsed_date_to
            )
        else:
            date_filter = "{parsed_date_from} {parsed_date_to}".format(
                parsed_date_from=parsed_date_from, parsed_date_to=parsed_date_to
            )

        return date_filter, query_params

    def _get_entity_query(self) -> Tuple[str, Dict]:
        entity_params, entity_format_params = get_entity_filtering_params(
            allowed_entities=[self._entity],
            team_id=self._team_id,
            table_name=self.EVENT_TABLE_ALIAS,
            person_properties_mode=PersonPropertiesMode.DIRECT_ON_EVENTS
            if self._using_person_on_events
            else PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
            hogql_context=self._filter.hogql_context,
        )

        return entity_format_params["entity_query"], entity_params

    @cached_property
    def _person_query(self):
        return PersonQuery(
            self._filter,
            self._team_id,
            self._column_optimizer,
            extra_fields=self._extra_person_fields,
            entity=self._entity,
        )
