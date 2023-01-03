import json
from typing import Any, Dict, List, TypedDict

from posthog.models.filters.properties_timeline_filter import PropertiesTimelineFilter
from posthog.models.person.person import Person
from posthog.models.property.util import extract_tables_and_properties, get_single_or_multi_property_string_expr
from posthog.models.team.team import Team
from posthog.queries.insight import insight_sync_execute
from posthog.queries.trends.trends_actors import handle_data_interval_for_data_point_actors

from .properties_timeline_event_query import PropertiesTimelineEventQuery


class PropertiesTimelinePoint(TypedDict):
    timestamp: str
    properties: Dict[str, Any]
    relevant_event_count: int


class PropertiesTimelineResult(TypedDict):
    points: List[PropertiesTimelinePoint]
    crucial_property_keys: List[str]
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
            person_properties AS properties,
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
    def run(self, filter: PropertiesTimelineFilter, team: Team, person: Person) -> PropertiesTimelineResult:
        filter = handle_data_interval_for_data_point_actors(filter)

        event_query = PropertiesTimelineEventQuery(
            filter=filter,
            team=team,
        )

        event_query_sql, event_query_params = event_query.get_query()
        params = {**event_query_params, "person_id": person.uuid}

        crucial_property_keys = [
            property_key
            for property_key, property_type, property_group_type_index in extract_tables_and_properties(
                filter.property_groups.flat
            )
            if property_type == "person"
        ]

        crucial_property_columns = get_single_or_multi_property_string_expr(
            crucial_property_keys,
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

        raw_query_result = insight_sync_execute(formatted_sql, params, query_type="properties_timeline")

        return PropertiesTimelineResult(
            points=[
                PropertiesTimelinePoint(
                    timestamp=timestamp,
                    properties=json.loads(properties),
                    relevant_event_count=relevant_event_count,
                )
                for timestamp, properties, relevant_event_count in raw_query_result
            ],
            crucial_property_keys=crucial_property_keys,
            effective_date_from=event_query.effective_date_from.isoformat(),
            effective_date_to=event_query.effective_date_to.isoformat(),
        )
