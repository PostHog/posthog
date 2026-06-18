from typing import Any

from posthog.schema import PersonsOnEventsMode

from posthog.models.property.util import get_property_string_expr
from posthog.queries.trends.trends_event_query_base import TrendsEventQueryBase


class TrendsEventQuery(TrendsEventQueryBase):
    def get_query(self) -> tuple[str, dict[str, Any]]:
        person_id_field = ""
        if self._should_join_distinct_ids:
            person_id_field = f", {self._person_id_alias} as person_id"
        elif self._person_on_events_mode == PersonsOnEventsMode.PERSON_ID_NO_OVERRIDE_PROPERTIES_ON_EVENTS:
            person_id_field = f", {self.EVENT_TABLE_ALIAS}.person_id as person_id"

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
                    + get_property_string_expr(
                        "events",
                        property,
                        f"'{property}'",
                        "properties",
                        table_alias="e",
                    )[0]
                    + f" as {property}"
                    for property in self._extra_event_properties
                ]
            )
            + person_id_field
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
            + (
                " ".join(
                    f", {self.EVENT_TABLE_ALIAS}.{column_name} as {column_name}" for column_name in self._extra_fields
                )
            )
            + (self._get_extra_person_columns())
        )

        base_query, params = super().get_query_base()

        return f"SELECT {_fields} {base_query}", params

    def _get_extra_person_columns(self) -> str:
        if self._person_on_events_mode != PersonsOnEventsMode.DISABLED:
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
