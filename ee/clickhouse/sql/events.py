from ee.kafka.topics import KAFKA_EVENTS

from .clickhouse import KAFKA_COLUMNS, STORAGE_POLICY, kafka_engine, table_engine

DROP_EVENTS_TABLE_SQL = """
DROP TABLE events
"""

DROP_EVENTS_WITH_ARRAY_PROPS_TABLE_SQL = """
DROP TABLE events_with_array_props_view
"""

DROP_MAT_EVENTS_WITH_ARRAY_PROPS_TABLE_SQL = """
DROP TABLE events_with_array_props_mv
"""

DROP_MAT_EVENTS_PROP_TABLE_SQL = """
DROP TABLE events_properties_view
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
    {extra_fields}
) ENGINE = {engine} 
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
    storage_policy=STORAGE_POLICY,
)

KAFKA_EVENTS_TABLE_SQL = EVENTS_TABLE_BASE_SQL.format(
    table_name="kafka_" + EVENTS_TABLE, engine=kafka_engine(topic=KAFKA_EVENTS), extra_fields=""
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
    ewap.uuid,
    ewap.event,
    ewap.properties,
    ewap.timestamp,
    ewap.team_id,
    ewap.distinct_id,
    ewap.elements_chain,
    ewap.created_at
FROM events_with_array_props_view as ewap
"""

GET_EVENTS_BY_TEAM_SQL = """
SELECT
    ewap.uuid,
    ewap.event,
    ewap.properties,
    ewap.timestamp,
    ewap.team_id,
    ewap.distinct_id,
    ewap.elements_chain,
    ewap.created_at
FROM events_with_array_props_view as ewap WHERE team_id = %(team_id)s
"""

EVENTS_WITH_PROPS_TABLE_SQL = """
CREATE TABLE events_with_array_props_view
(
    uuid UUID,
    event VARCHAR,
    properties VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    elements_chain VARCHAR,
    created_at DateTime64,
    array_property_keys Array(VARCHAR),
    array_property_values Array(VARCHAR),
    _timestamp UInt64,
    _offset UInt64
) ENGINE = {engine} 
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), distinct_id, uuid)
SAMPLE BY uuid 
{storage_policy}
""".format(
    engine=table_engine("events_with_array_props_view", "_timestamp"), storage_policy=STORAGE_POLICY
)

MAT_EVENTS_WITH_PROPS_TABLE_SQL = """
CREATE MATERIALIZED VIEW events_with_array_props_mv
TO events_with_array_props_view
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

MAT_EVENT_PROP_TABLE_SQL = """
CREATE MATERIALIZED VIEW events_properties_view
ENGINE = MergeTree()
ORDER BY (team_id, key, value, event_id)
AS SELECT uuid as event_id,
team_id,
array_property_keys as key,
array_property_values as value
from events_with_array_props_view
ARRAY JOIN array_property_keys, array_property_values
"""

SELECT_PROP_VALUES_SQL = """
SELECT DISTINCT trim(BOTH '\"' FROM value) FROM events_properties_view where key = %(key)s AND team_id = %(team_id)s LIMIT 50
"""

SELECT_PROP_VALUES_SQL_WITH_FILTER = """
SELECT DISTINCT trim(BOTH '\"' FROM value) FROM events_properties_view where key = %(key)s AND team_id = %(team_id)s AND trim(BOTH '\"' FROM value) LIKE %(value)s LIMIT 50
"""

SELECT_EVENT_WITH_ARRAY_PROPS_SQL = """
SELECT
    ewap.uuid,
    ewap.event,
    ewap.properties,
    ewap.timestamp,
    ewap.team_id,
    ewap.distinct_id,
    ewap.elements_chain,
    ewap.created_at
FROM
    events_with_array_props_view ewap
where ewap.team_id = %(team_id)s
{conditions}
ORDER BY toDate(ewap.timestamp) DESC, ewap.timestamp DESC {limit}
"""

SELECT_EVENT_WITH_PROP_SQL = """
SELECT
    ewap.uuid,
    ewap.event,
    ewap.properties,
    ewap.timestamp,
    ewap.team_id,
    ewap.distinct_id,
    ewap.elements_chain,
    ewap.created_at
FROM events_with_array_props_view AS ewap
WHERE 
team_id = %(team_id)s
{conditions}
{filters}
ORDER BY toDate(ewap.timestamp) DESC, ewap.timestamp DESC {limit}
"""

SELECT_ONE_EVENT_SQL = """
SELECT
    ewap.uuid,
    ewap.event,
    ewap.properties,
    ewap.timestamp,
    ewap.team_id,
    ewap.distinct_id,
    ewap.elements_chain,
    ewap.created_at
FROM events_with_array_props_view WHERE uuid = %(event_id)s AND team_id = %(team_id)s
"""

EVENT_PROP_CLAUSE = """
SELECT event_id
FROM events_properties_view AS ep
WHERE {filters} AND team_id = %(team_id)s
"""

GET_EARLIEST_TIMESTAMP_SQL = """
SELECT timestamp from events order by toDate(timestamp), timestamp limit 1
"""

NULL_SQL = """
SELECT toUInt16(0) AS total, {interval}(toDateTime('{date_to}') - number * {seconds_in_interval}) as day_start from numbers({num_intervals})
"""

NULL_BREAKDOWN_SQL = """
SELECT toUInt16(0) AS total, {interval}(toDateTime('{date_to}') - number * {seconds_in_interval}) as day_start, breakdown_value from numbers({num_intervals})
"""

EVENT_JOIN_PERSON_SQL = """
INNER JOIN person_distinct_id as pid ON events.distinct_id = pid.distinct_id
"""

EVENT_JOIN_PROPERTY_WITH_KEY_SQL = """
INNER JOIN (SELECT event_id, toInt64OrNull(value) as value FROM events_properties_view WHERE team_id = %(team_id)s AND key = %(join_property_key)s AND value IS NOT NULL) as pid ON events.uuid = pid.event_id
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
