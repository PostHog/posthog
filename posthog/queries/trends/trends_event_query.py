from typing import Any, Dict, Tuple

from posthog.models.property.util import get_property_string_expr
from posthog.queries.trends.trends_event_query_base import TrendsEventQueryBase


class TrendsEventQuery(TrendsEventQueryBase):
    def get_query(self) -> Tuple[str, Dict[str, Any]]:
        _fields = (
            f"{self.EVENT_TABLE_ALIAS}.timestamp as timestamp"
            + (
                " ".join(
                    f', {self.EVENT_TABLE_ALIAS}."{column_name}" as "{column_name}"'
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
            + (
                f", {self.SESSION_TABLE_ALIAS}.session_duration as session_duration"
                if self._should_join_sessions
                else ""
            )
            + (
                f", {self.SESSION_TABLE_ALIAS}.$session_id as $session_id"
                if self._should_join_sessions
                and "$session_id" not in self._extra_event_properties
                and "$session_id" not in self._column_optimizer.event_columns_to_query
                else ""
            )
            + (f", {self.EVENT_TABLE_ALIAS}.distinct_id as distinct_id" if self._aggregate_users_by_distinct_id else "")
            + (f", {self.EVENT_TABLE_ALIAS}.person_id as person_id" if self._using_person_on_events else "")
            + (
                " ".join(
                    f", {self.EVENT_TABLE_ALIAS}.{column_name} as {column_name}" for column_name in self._extra_fields
                )
            )
            + (self._get_extra_person_columns())
        )

        base_query, params = super().get_query()

        return f"SELECT {_fields} {base_query}", params

    def _get_extra_person_columns(self) -> str:
        if self._using_person_on_events:
            return " ".join(
                ", {extract} as {column_name}".format(
                    extract=get_property_string_expr(
                        "events",
                        column_name,
                        var=f"'{column_name}'",
                        allow_denormalized_props=False,
                        column="person_properties",
                        table_alias=self.EVENT_TABLE_ALIAS,
                        materialised_table_column="person_properties",
                    ),
                    column_name=column_name,
                )
                for column_name in self._extra_person_fields
            )
        else:
            return " ".join(
                f", {self.PERSON_TABLE_ALIAS}.{column_name} as {column_name}"
                for column_name in self._extra_person_fields
            )
