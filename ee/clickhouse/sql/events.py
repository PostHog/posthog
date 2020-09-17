from .clickhouse import STORAGE_POLICY, table_engine

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

EVENTS_TABLE_SQL = """
CREATE TABLE events
(
    id UUID,
    event VARCHAR,
    properties VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    team_id Int32,
    distinct_id VARCHAR,
    elements_hash VARCHAR,
    created_at DateTime
) ENGINE = {engine} 
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, timestamp, distinct_id, id)
SAMPLE BY id 
{storage_policy}
""".format(
    engine=table_engine("events"), storage_policy=STORAGE_POLICY
)

INSERT_EVENT_SQL = """
INSERT INTO events SELECT generateUUIDv4(), %(event)s, %(properties)s, %(timestamp)s, %(team_id)s, %(distinct_id)s, %(elements_hash)s, now()
"""

GET_EVENTS_SQL = """
SELECT * FROM events_with_array_props_view
"""

GET_EVENTS_BY_TEAM_SQL = """
SELECT * FROM events_with_array_props_view WHERE team_id = %(team_id)s
"""

EVENTS_WITH_PROPS_TABLE_SQL = """
CREATE TABLE events_with_array_props_view
(
    id UUID,
    event VARCHAR,
    properties VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    team_id Int32,
    distinct_id VARCHAR,
    elements_hash VARCHAR,
    created_at DateTime,
    array_property_keys Array(VARCHAR),
    array_property_values Array(VARCHAR)
) ENGINE = {engine} 
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, created_at, id)
SAMPLE BY id
{storage_policy}
""".format(
    engine=table_engine("events_with_array_props_view"), storage_policy=STORAGE_POLICY
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
arrayMap(k -> toString(k.2), JSONExtractKeysAndValuesRaw(properties)) array_property_values
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

EVENT_PROP_CLAUSE = """
SELECT event_id
FROM events_properties_view AS ep
WHERE {filters} AND team_id = %(team_id)s
"""

GET_EARLIEST_TIMESTAMP_SQL = """
SELECT timestamp from events order by timestamp limit 1
"""

NULL_SQL = """
SELECT toUInt16(0) AS total, {interval}(toDateTime('{date_to}') - number * {seconds_in_interval}) as day_start from numbers({num_intervals})
"""

NULL_BREAKDOWN_SQL = """
SELECT toUInt16(0) AS total, {interval}(toDateTime('{date_to}') - number * {seconds_in_interval}) as day_start, value from numbers({num_intervals})
"""

EVENT_JOIN_PERSON_SQL = """
INNER JOIN person_distinct_id as pid ON events.distinct_id = pid.distinct_id
"""

EVENT_JOIN_PROPERTY_WITH_KEY_SQL = """
INNER JOIN (SELECT event_id, toInt64OrNull(value) as value FROM events_properties_view WHERE team_id = %(team_id)s AND key = %(join_property_key)s AND value IS NOT NULL) as pid ON events.id = pid.event_id
"""
