import json
from typing import Any, Dict, List, TypedDict

from posthog.models.filters.properties_timeline_filter import PropertiesTimelineFilter
from posthog.models.person.person import Person
from posthog.models.property.util import extract_tables_and_properties, get_single_or_multi_property_string_expr
from posthog.models.team.team import Team
from posthog.queries.insight import insight_sync_execute

from .properties_timeline_event_query import PropertiesTimelineEventQuery


class PropertiesTimelinePoint(TypedDict):
    timestamp: str
    properties: Dict[str, Any]
    relevant_events_since_previous_point: int


PROPERTIES_TIMELINE_SQL = """
SELECT
    timestamp,
    properties,
    if(
        NOT is_pre_range AND start_event_number = 1,
        0, /* If the event is first-ever for this person, relevant_events_since_previous_point will be 0 */
        start_event_number - previous_start_event_number
    ) AS relevant_events_since_previous_point
FROM (
    SELECT
        timestamp,
        properties,
        is_pre_range,
        start_event_number,
        lagInFrame(start_event_number) OVER person_points AS previous_start_event_number
    FROM (
        SELECT
            timestamp,
            person_properties AS properties,
            is_pre_range,
            {crucial_property_columns} AS relevant_property_values, -- TODO make this dynamic
            lagInFrame({crucial_property_columns}) OVER person_events AS previous_relevant_property_values,
            row_number() OVER person_events AS start_event_number
        FROM ({event_query})
        WINDOW person_events AS (ORDER BY timestamp ASC ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
    )
    -- TODO union to including pre-timeline properties instead of `start_event_number = 1`
    WHERE start_event_number = 1 OR relevant_property_values != previous_relevant_property_values
    WINDOW person_points AS (ORDER BY timestamp ASC ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
)
"""


class PropertiesTimeline:
    def run(self, filter: PropertiesTimelineFilter, team: Team, person: Person) -> List[PropertiesTimelinePoint]:
        event_query = PropertiesTimelineEventQuery(
            filter=filter,
            team=team,
        )

        event_query_sql, event_query_params = event_query.get_query()
        params = {**event_query_params, "person_id": person.uuid}

        property_keys = [
            property_key
            for property_key, property_type, property_group_type_index in extract_tables_and_properties(
                filter.property_groups.flat
            )
            if property_type == "person"
        ]

        crucial_property_columns = get_single_or_multi_property_string_expr(
            property_keys,
            query_alias=None,
            table="events",
            column="person_properties",
            allow_denormalized_props=True,
            materialised_table_column="person_properties",
        )

        formatted_sql = PROPERTIES_TIMELINE_SQL.format(
            event_query=event_query_sql,
            crucial_property_columns=crucial_property_columns,
        )

        raw_result = insight_sync_execute(formatted_sql, params, query_type="properties_timeline")

        parsed_result = [
            PropertiesTimelinePoint(
                timestamp=timestamp,
                properties=json.loads(properties),
                relevant_events_since_previous_point=relevant_events_since_previous_point,
            )
            for timestamp, properties, relevant_events_since_previous_point in raw_result
        ]

        return parsed_result
