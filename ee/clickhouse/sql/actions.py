from .clickhouse import STORAGE_POLICY, table_engine

FILTER_EVENT_BY_ACTION_SQL = """
SELECT
    events.uuid,
    events.event,
    events.properties,
    events.timestamp,
    events.team_id,
    events.distinct_id,
    events.elements_chain,
    events.created_at
FROM events where uuid IN (
    SELECT uuid FROM {table_name}
)
"""


def create_action_mapping_table_sql(table_name: str) -> str:
    return """
        CREATE TABLE IF NOT EXISTS {table_name}
        (
            uuid UUID
        )ENGINE = {engine}
        ORDER BY (uuid)
        {storage_policy}
        """.format(
        table_name=table_name, engine=table_engine(table_name), storage_policy=STORAGE_POLICY
    )


INSERT_INTO_ACTION_TABLE = """
INSERT INTO {table_name} SELECT uuid FROM ({query})
"""

ACTION_QUERY = """
SELECT
    events.uuid,
    events.event,
    events.properties,
    events.timestamp,
    events.team_id,
    events.distinct_id,
    events.elements_chain,
    events.created_at
FROM events
WHERE uuid IN {action_filter}
AND events.team_id = %(team_id)s
ORDER BY events.timestamp DESC
"""

# action_filter — concatenation of element_action_filters and event_action_filters

ELEMENT_ACTION_FILTER = """
(
    SELECT uuid FROM events WHERE 
        team_id = %(team_id)s
        {selector_regex}
        {attributes_regex}
        {tag_name_regex}
        {event_filter}
)
"""


EVENT_ACTION_FILTER = """
(
    SELECT uuid from events_with_array_props_view WHERE uuid IN (
        SELECT event_id
        FROM events_properties_view AS ep
        WHERE team_id = %(team_id)s {property_filter}
    ) {event_filter}
)
"""

EVENT_NO_PROP_FILTER = """
(
    SELECT uuid FROM events_with_array_props_view where team_id = %(team_id)s {event_filter}
)
"""
