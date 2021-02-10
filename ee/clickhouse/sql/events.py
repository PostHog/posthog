from ee.kafka_client.topics import KAFKA_EVENTS

from .clickhouse import KAFKA_COLUMNS, STORAGE_POLICY, kafka_engine, table_engine

DROP_EVENTS_TABLE_SQL = """
DROP TABLE events
"""

DROP_EVENTS_WITH_ARRAY_PROPS_TABLE_SQL = """
DROP TABLE events_with_array_props_view
"""


EVENTS_TABLE = "events"

EVENTS_TABLE_BASE_SQL = """
CREATE TABLE {table_name} 
(
    uuid UUID,
    event VARCHAR,
    properties VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    elements_chain VARCHAR,
    created_at DateTime64(6, 'UTC')
    {materialized_columns}
    {extra_fields}
) ENGINE = {engine} 
"""

EVENTS_TABLE_MATERIALIZED_COLUMNS = """
    , properties_issampledevent VARCHAR materialized trim(BOTH '\"' FROM JSONExtractRaw(properties, 'isSampledEvent'))
    , properties_currentscreen VARCHAR materialized trim(BOTH '\"' FROM JSONExtractRaw(properties, 'currentScreen'))
    , properties_objectname VARCHAR materialized trim(BOTH '\"' FROM JSONExtractRaw(properties, 'objectName'))
    , properties_test_prop VARCHAR materialized trim(BOTH '\"' FROM JSONExtractRaw(properties, 'test_prop'))
"""

EVENTS_TABLE_SQL = (
    EVENTS_TABLE_BASE_SQL
    + """PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), distinct_id, uuid)
SAMPLE BY uuid 
{storage_policy}
"""
).format(
    table_name=EVENTS_TABLE,
    engine=table_engine(EVENTS_TABLE, "_timestamp"),
    extra_fields=KAFKA_COLUMNS,
    materialized_columns=EVENTS_TABLE_MATERIALIZED_COLUMNS,
    storage_policy=STORAGE_POLICY,
)

KAFKA_EVENTS_TABLE_SQL = EVENTS_TABLE_BASE_SQL.format(
    table_name="kafka_" + EVENTS_TABLE,
    engine=kafka_engine(topic=KAFKA_EVENTS, serialization="Protobuf", proto_schema="events:Event"),
    extra_fields="",
    materialized_columns="",
)

EVENTS_TABLE_MV_SQL = """
CREATE MATERIALIZED VIEW {table_name}_mv 
TO {table_name} 
AS SELECT
uuid,
event,
properties,
timestamp,
team_id,
distinct_id,
elements_chain,
created_at,
_timestamp,
_offset
FROM kafka_{table_name} 
""".format(
    table_name=EVENTS_TABLE
)

INSERT_EVENT_SQL = """
INSERT INTO events SELECT %(uuid)s, %(event)s, %(properties)s, %(timestamp)s, %(team_id)s, %(distinct_id)s, %(elements_chain)s, %(created_at)s, now(), 0
"""

GET_EVENTS_SQL = """
SELECT
    uuid,
    event,
    properties,
    timestamp,
    team_id,
    distinct_id,
    elements_chain,
    created_at
FROM events
"""

GET_EVENTS_BY_TEAM_SQL = """
SELECT
    uuid,
    event,
    properties,
    timestamp,
    team_id,
    distinct_id,
    elements_chain,
    created_at
FROM events WHERE team_id = %(team_id)s
"""

EVENTS_WITH_PROPS_TABLE_SQL = """
CREATE VIEW events_with_array_props_view
AS SELECT
uuid,
event,
properties,
timestamp,
team_id,
distinct_id,
elements_chain,
created_at,
arrayMap(k -> toString(k.1), JSONExtractKeysAndValuesRaw(properties)) array_property_keys,
arrayMap(k -> toString(k.2), JSONExtractKeysAndValuesRaw(properties)) array_property_values,
_timestamp,
_offset
FROM events
"""

SELECT_PROP_VALUES_SQL = """
SELECT DISTINCT trim(BOTH '\"' FROM JSONExtractRaw(properties, %(key)s)) FROM events where JSONHas(properties, %(key)s) AND team_id = %(team_id)s {parsed_date_from} {parsed_date_to} LIMIT 10
"""

SELECT_PROP_VALUES_SQL_WITH_FILTER = """
SELECT DISTINCT trim(BOTH '\"' FROM JSONExtractRaw(properties, %(key)s)) FROM events where team_id = %(team_id)s AND trim(BOTH '\"' FROM JSONExtractRaw(properties, %(key)s)) LIKE %(value)s {parsed_date_from} {parsed_date_to} LIMIT 10
"""

SELECT_EVENT_WITH_ARRAY_PROPS_SQL = """
SELECT
    uuid,
    event,
    properties,
    timestamp,
    team_id,
    distinct_id,
    elements_chain,
    created_at
FROM
    events
where team_id = %(team_id)s
{conditions}
ORDER BY toDate(timestamp) DESC, timestamp DESC {limit}
"""

SELECT_EVENT_WITH_PROP_SQL = """
SELECT
    uuid,
    event,
    properties,
    timestamp,
    team_id,
    distinct_id,
    elements_chain,
    created_at
FROM events
WHERE 
team_id = %(team_id)s
{conditions}
{filters}
ORDER BY toDate(timestamp) DESC, timestamp DESC {limit}
"""

SELECT_ONE_EVENT_SQL = """
SELECT
    uuid,
    event,
    properties,
    timestamp,
    team_id,
    distinct_id,
    elements_chain,
    created_at
FROM events WHERE uuid = %(event_id)s AND team_id = %(team_id)s
"""

GET_EARLIEST_TIMESTAMP_SQL = """
SELECT timestamp from events WHERE team_id = %(team_id)s order by toDate(timestamp), timestamp limit 1
"""

NULL_SQL = """
SELECT toUInt16(0) AS total, {interval}(toDateTime('{date_to}') - number * {seconds_in_interval}) as day_start from numbers({num_intervals})
"""

NULL_BREAKDOWN_SQL = """
SELECT toUInt16(0) AS total, {interval}(toDateTime('{date_to}') - number * {seconds_in_interval}) as day_start, breakdown_value from numbers({num_intervals})
"""

EVENT_JOIN_PERSON_SQL = """
INNER JOIN (SELECT person_id, distinct_id FROM person_distinct_id WHERE team_id = %(team_id)s) as pid ON events.distinct_id = pid.distinct_id
"""

GET_EVENTS_WITH_PROPERTIES = """
SELECT * FROM events WHERE 
team_id = %(team_id)s
{filters}
{order_by}
"""

EXTRACT_TAG_REGEX = "extract(elements_chain, '^(.*?)[.|:]')"
EXTRACT_TEXT_REGEX = "extract(elements_chain, 'text=\"(.*?)\"')"

ELEMENT_TAG_COUNT = """
SELECT concat('<', {tag_regex}, '> ', {text_regex}) AS tag_name,
       events.elements_chain,
       count(*) as tag_count
FROM events
WHERE events.team_id = %(team_id)s AND event = '$autocapture'
GROUP BY tag_name, elements_chain
ORDER BY tag_count desc, tag_name
LIMIT %(limit)s
""".format(
    tag_regex=EXTRACT_TAG_REGEX, text_regex=EXTRACT_TEXT_REGEX
)

GET_CUSTOM_EVENTS = """
SELECT DISTINCT event FROM events where team_id = %(team_id)s AND event NOT IN ['$autocapture', '$pageview', '$identify', '$pageleave', '$screen']
"""

GET_PROPERTIES_VOLUME = """
    SELECT arrayJoin(array_property_keys) as key, count(1) as count FROM events_with_array_props_view WHERE team_id = %(team_id)s AND timestamp > %(timestamp)s GROUP BY key ORDER BY count DESC
"""

GET_EVENTS_VOLUME = "SELECT event, count(1) as count FROM events WHERE team_id = %(team_id)s AND timestamp > %(timestamp)s GROUP BY event ORDER BY count DESC"
