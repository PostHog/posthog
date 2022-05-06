from typing import Any, Dict, Tuple

from ee.clickhouse.models.entity import get_entity_filtering_params
from ee.clickhouse.models.property import get_property_string_expr
from ee.clickhouse.queries.event_query import EnterpriseEventQuery
from ee.clickhouse.queries.trends.util import get_active_user_params
from posthog.constants import MONTHLY_ACTIVE, WEEKLY_ACTIVE, PropertyOperatorType
from posthog.models import Entity
from posthog.models.filters.filter import Filter
from posthog.models.filters.mixins.utils import cached_property
from posthog.queries.person_query import PersonQuery
from posthog.queries.util import date_from_clause, get_time_diff, get_trunc_func_ch, parse_timestamps


class TrendsEventQuery(EnterpriseEventQuery):
    _entity: Entity
    _filter: Filter

    def __init__(self, entity: Entity, *args, **kwargs):
        self._entity = entity
        super().__init__(*args, **kwargs)

    def get_query(self) -> Tuple[str, Dict[str, Any]]:
        _fields = (
            f"{self.EVENT_TABLE_ALIAS}.timestamp as timestamp"
            + (
                " ".join(
                    f", {self.EVENT_TABLE_ALIAS}.{column_name} as {column_name}"
                    for column_name in self._column_optimizer.event_columns_to_query
                )
            )
            + " ".join(
                [
                    ", "
                    + get_property_string_expr("events", property, f"'{property}'", "properties", table_alias="e")[0]
                    + f" as {property}"
                    for property in self._extra_event_properties
                ]
            )
            + (f", {self.DISTINCT_ID_TABLE_ALIAS}.person_id as person_id" if self._should_join_distinct_ids else "")
            + (f", {self.EVENT_TABLE_ALIAS}.distinct_id as distinct_id" if self._aggregate_users_by_distinct_id else "")
            + (
                " ".join(
                    f", {self.EVENT_TABLE_ALIAS}.{column_name} as {column_name}" for column_name in self._extra_fields
                )
            )
            + (
                " ".join(
                    f", {self.PERSON_TABLE_ALIAS}.{column_name} as {column_name}"
                    for column_name in self._extra_person_fields
                )
            )
        )

        date_query, date_params = self._get_date_filter()
        self.params.update(date_params)

        prop_query, prop_params = self._get_prop_groups(
            self._filter.property_groups.combine_property_group(PropertyOperatorType.AND, self._entity.property_groups)
        )

        self.params.update(prop_params)

        entity_query, entity_params = self._get_entity_query()
        self.params.update(entity_params)

        person_query, person_params = self._get_person_query()
        self.params.update(person_params)

        groups_query, groups_params = self._get_groups_query()
        self.params.update(groups_params)

        query = f"""
            SELECT {_fields} FROM events {self.EVENT_TABLE_ALIAS}
            {self._get_distinct_id_query()}
            {person_query}
            {groups_query}
            WHERE team_id = %(team_id)s
            {entity_query}
            {date_query}
            {prop_query}
        """

        return query, self.params

    def _determine_should_join_distinct_ids(self) -> None:
        if self._entity.math == "dau" and not self._aggregate_users_by_distinct_id:
            self._should_join_distinct_ids = True

    def _get_date_filter(self) -> Tuple[str, Dict]:
        date_filter = ""
        date_params: Dict[str, Any] = {}
        interval_annotation = get_trunc_func_ch(self._filter.interval)
        _, _, round_interval = get_time_diff(
            self._filter.interval, self._filter.date_from, self._filter.date_to, team_id=self._team_id
        )
        _, parsed_date_to, date_params = parse_timestamps(filter=self._filter, team=self._team)
        parsed_date_from = date_from_clause(interval_annotation, round_interval)

        self.parsed_date_from = parsed_date_from
        self.parsed_date_to = parsed_date_to

        if self._entity.math in [WEEKLY_ACTIVE, MONTHLY_ACTIVE]:
            date_filter = "{parsed_date_from_prev_range} {parsed_date_to}"
            format_params = get_active_user_params(self._filter, self._entity, self._team_id)
            self.active_user_params = format_params

            date_filter = date_filter.format(**format_params, parsed_date_to=parsed_date_to)
        else:
            date_filter = "{parsed_date_from} {parsed_date_to}".format(
                parsed_date_from=parsed_date_from, parsed_date_to=parsed_date_to
            )

        return date_filter, date_params

    def _get_entity_query(self) -> Tuple[str, Dict]:
        entity_params, entity_format_params = get_entity_filtering_params(
            entity=self._entity, team_id=self._team_id, table_name=self.EVENT_TABLE_ALIAS
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
