from ee.kafka.topics import KAFKA_EVENTS

from .clickhouse import STORAGE_POLICY, kafka_engine, table_engine

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
    id UUID,
    event VARCHAR,
    properties VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    elements_hash VARCHAR,
    created_at DateTime64(6, 'UTC'),
    _timestamp UInt64,
    _offset UInt64
) ENGINE = {engine} 
"""

EVENTS_TABLE_SQL = (
    EVENTS_TABLE_BASE_SQL
    + """PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), distinct_id, id)
SAMPLE BY id 
{storage_policy}
"""
).format(table_name=EVENTS_TABLE, engine=table_engine(EVENTS_TABLE, "_timestamp"), storage_policy=STORAGE_POLICY)

KAFKA_EVENTS_TABLE_SQL = EVENTS_TABLE_BASE_SQL.format(
    table_name="kafka_" + EVENTS_TABLE, engine=kafka_engine(topic=KAFKA_EVENTS)
)

EVENTS_TABLE_MV_SQL = """
CREATE MATERIALIZED VIEW {table_name}_mv 
TO {table_name} 
AS SELECT
id,
event,
properties,
timestamp,
team_id,
distinct_id,
elements_hash,
created_at,
_timestamp,
_offset
FROM kafka_{table_name} 
""".format(
    table_name=EVENTS_TABLE
)

INSERT_EVENT_SQL = """
INSERT INTO events SELECT %(id)s, %(event)s, %(properties)s, %(timestamp)s, %(team_id)s, %(distinct_id)s, %(elements_hash)s, %(created_at)s, now(), 0
"""

GET_EVENTS_SQL = """
SELECT * FROM events_with_array_props_view
"""

EVENTS_WITH_PROPS_TABLE_SQL = """
CREATE TABLE events_with_array_props_view
(
    id UUID,
    event VARCHAR,
    properties VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    team_id Int64,
    distinct_id VARCHAR,
    elements_hash VARCHAR,
    created_at DateTime,
    array_property_keys Array(VARCHAR),
    array_property_values Array(VARCHAR),
    _timestamp UInt64,
    _offset UInt64
) ENGINE = {engine} 
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, toDate(timestamp), distinct_id, id)
SAMPLE BY id
{storage_policy}
""".format(
    engine=table_engine("events_with_array_props_view", "_timestamp"), storage_policy=STORAGE_POLICY
)

SELECT_EVENT_WITH_ARRAY_PROPS_SQL = """
SELECT * FROM events_with_array_props_view where team_id = %(team_id)s {conditions} ORDER BY timestamp desc {limit}
"""

MAT_EVENTS_WITH_PROPS_TABLE_SQL = """
CREATE MATERIALIZED VIEW events_with_array_props_mv
TO events_with_array_props_view
AS SELECT
id,
event,
properties,
timestamp,
team_id,
distinct_id,
elements_hash,
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
AS SELECT id as event_id,
team_id,
array_property_keys as key,
array_property_values as value
from events_with_array_props_view
ARRAY JOIN array_property_keys, array_property_values
"""

SELECT_PROP_VALUES_SQL = """
SELECT DISTINCT value FROM events_properties_view where key = %(key)s AND team_id = %(team_id)s LIMIT 50
"""

SELECT_EVENT_WITH_PROP_SQL = """
SELECT
    *
FROM events_with_array_props_view AS ewap
WHERE id IN
(
    SELECT event_id
    FROM events_properties_view AS ep
    WHERE {filters} AND team_id = %(team_id)s
) {conditions} {limit}
"""
