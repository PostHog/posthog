from typing import Any, Dict, Tuple

from ee.clickhouse.models.entity import get_entity_filtering_params
from ee.clickhouse.queries.event_query import ClickhouseEventQuery
from ee.clickhouse.queries.person_query import ClickhousePersonQuery
from ee.clickhouse.queries.trends.util import get_active_user_params
from ee.clickhouse.queries.util import date_from_clause, get_time_diff, get_trunc_func_ch, parse_timestamps
from ee.clickhouse.query_builder import SQL, SQLFragment
from posthog.constants import MONTHLY_ACTIVE, WEEKLY_ACTIVE
from posthog.models import Entity
from posthog.models.filters.filter import Filter


class TrendsEventQuery(ClickhouseEventQuery):
    _entity: Entity
    _filter: Filter

    def __init__(self, entity: Entity, *args, **kwargs):
        self._entity = entity
        super().__init__(*args, **kwargs)
        self._person_query = ClickhousePersonQuery(
            self._filter,
            self._team_id,
            self._column_optimizer,
            extra_fields=kwargs.get("extra_person_fields", []),
            entity=entity,
        )

    def get_query(self) -> SQLFragment:
        _fields = SQL(
            f"{self.EVENT_TABLE_ALIAS}.timestamp as timestamp"
            + (
                " ".join(
                    f", {self.EVENT_TABLE_ALIAS}.{column_name} as {column_name}"
                    for column_name in self._column_optimizer.event_columns_to_query
                )
            )
            + (f", {self.DISTINCT_ID_TABLE_ALIAS}.person_id as person_id" if self._should_join_distinct_ids else "")
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
        prop_query = self._get_props([*self._filter.properties, *self._entity.properties])

        return SQL(
            """
            SELECT {_fields} FROM events {self.EVENT_TABLE_ALIAS!s}
            {self._get_disintct_id_query()}
            {self._get_person_query()}
            {self._get_groups_query()}
            WHERE team_id = %(team_id)s
            {self._get_entity_query()}
            {self._get_date_filter()}
            {prop_query}
            """,
            {"team_id": self._team_id},
        )

    def _determine_should_join_distinct_ids(self) -> None:
        if self._entity.math == "dau":
            self._should_join_distinct_ids = True

    def _get_date_filter(self) -> SQLFragment:
        date_filter = ""
        date_params: Dict[str, Any] = {}
        interval_annotation = get_trunc_func_ch(self._filter.interval)
        _, _, round_interval = get_time_diff(
            self._filter.interval, self._filter.date_from, self._filter.date_to, team_id=self._team_id
        )
        _, parsed_date_to, date_params = parse_timestamps(filter=self._filter, team_id=self._team_id)
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

        return SQL(date_filter, date_params)

    def _get_entity_query(self) -> SQLFragment:
        entity_params, entity_format_params = get_entity_filtering_params(
            self._entity, self._team_id, table_name=self.EVENT_TABLE_ALIAS
        )

        return SQL(entity_format_params["entity_query"], entity_params)
