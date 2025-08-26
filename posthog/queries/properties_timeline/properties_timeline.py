import json
import datetime
from typing import Any, TypedDict, Union, cast

from posthog.models.filters.properties_timeline_filter import PropertiesTimelineFilter
from posthog.models.group.group import Group
from posthog.models.person.person import Person
from posthog.models.property.util import extract_tables_and_properties, get_single_or_multi_property_string_expr
from posthog.models.team.team import Team
from posthog.queries.insight import insight_sync_execute
from posthog.queries.trends.util import offset_time_series_date_by_interval

from .properties_timeline_event_query import PropertiesTimelineEventQuery


class PropertiesTimelinePoint(TypedDict):
    timestamp: str
    properties: dict[str, Any]
    relevant_event_count: int


class PropertiesTimelineResult(TypedDict):
    points: list[PropertiesTimelinePoint]
    crucial_property_keys: list[str]
    effective_date_from: str
    effective_date_to: str


PROPERTIES_TIMELINE_SQL = """
SELECT
    timestamp,
    properties,
    end_event_number - start_event_number AS relevant_event_count
FROM (
    SELECT
        timestamp,
        properties,
        start_event_number,
        leadInFrame(start_event_number) OVER (ORDER BY timestamp ASC ROWS BETWEEN CURRENT ROW AND 1 FOLLOWING) AS end_event_number
    FROM (
        SELECT
            timestamp,
            {actor_properties_column} AS properties,
            {crucial_property_columns} AS relevant_property_values,
            lagInFrame(relevant_property_values) OVER (ORDER BY timestamp ASC ROWS BETWEEN 1 PRECEDING AND CURRENT ROW) AS previous_relevant_property_values,
            row_number() OVER (ORDER BY timestamp ASC) AS start_event_number
        FROM ({event_query})
    )
    WHERE start_event_number = 1 OR relevant_property_values != previous_relevant_property_values OR timestamp IS NULL
)
WHERE timestamp IS NOT NULL /* Remove sentinel row */
"""


class PropertiesTimeline:
    def extract_crucial_property_keys(self, filter: PropertiesTimelineFilter) -> set[str]:
        is_filter_relevant = lambda property_type, property_group_type_index: (
            (property_type == "person")
            if filter.aggregation_group_type_index is None
            else (property_type == "group" and property_group_type_index == filter.aggregation_group_type_index)
        )

        property_filters = filter.property_groups.flat
        for event in filter.entities:
            property_filters.extend(event.property_groups.flat)
        all_property_identifiers = extract_tables_and_properties(property_filters)

        crucial_property_keys = {
            property_key
            for property_key, property_type, property_group_type_index in all_property_identifiers
            if is_filter_relevant(property_type, property_group_type_index)
        }

        if filter.breakdown and filter.breakdown_type == "person":
            if isinstance(filter.breakdown, list):
                crucial_property_keys.update(cast(list[str], filter.breakdown))
            else:
                crucial_property_keys.add(filter.breakdown)

        return crucial_property_keys

    def run(
        self, filter: PropertiesTimelineFilter, team: Team, actor: Union[Person, Group]
    ) -> PropertiesTimelineResult:
        if filter._date_from is not None and filter._date_to is not None and filter._date_from == filter._date_to:
            # Search for `offset_time_series_date_by_interval` in the `TrendsActors` class for context on this handling
            filter = filter.shallow_clone(
                {
                    "date_to": offset_time_series_date_by_interval(
                        cast(datetime.datetime, filter.date_from),
                        filter=filter,
                        team=team,
                    )
                }
            )

        event_query = PropertiesTimelineEventQuery(
            filter=filter,
            team=team,
        )
        event_query_sql, event_query_params = event_query.get_query()

        crucial_property_keys = self.extract_crucial_property_keys(filter)
        crucial_property_columns, crucial_property_params = get_single_or_multi_property_string_expr(
            sorted(crucial_property_keys),
            query_alias=None,
            table="events",
            column="person_properties",
            allow_denormalized_props=True,
            materialised_table_column="person_properties",
        )

        actor_properties_column = (
            "person_properties"
            if filter.aggregation_group_type_index is None
            else f"group_{filter.aggregation_group_type_index}_properties"
        )

        formatted_sql = PROPERTIES_TIMELINE_SQL.format(
            event_query=event_query_sql,
            crucial_property_columns=crucial_property_columns,
            actor_properties_column=actor_properties_column,
        )

        params = {
            **event_query_params,
            **crucial_property_params,
            "actor_id": actor.uuid if isinstance(actor, Person) else actor.group_key,
        }
        raw_query_result = insight_sync_execute(
            formatted_sql,
            {**params, **filter.hogql_context.values},
            query_type="properties_timeline",
            team_id=team.pk,
        )

        return PropertiesTimelineResult(
            points=[
                PropertiesTimelinePoint(
                    timestamp=timestamp,
                    properties=json.loads(properties),
                    relevant_event_count=relevant_event_count,
                )
                for timestamp, properties, relevant_event_count in raw_query_result
            ],
            crucial_property_keys=sorted(crucial_property_keys),
            effective_date_from=event_query.effective_date_from.isoformat(),
            effective_date_to=event_query.effective_date_to.isoformat(),
        )
