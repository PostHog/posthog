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
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (id, timestamp, intHash32(team_id))
SAMPLE BY intHash32(team_id)
"""

INSERT_EVENT_SQL = """
INSERT INTO events SELECT generateUUIDv4(), %(event)s, %(properties)s, parseDateTimeBestEffort(%(timestamp)s), %(team_id)s, %(distinct_id)s, %(element_hash)s, now()
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
    team_id Int32,
    distinct_id VARCHAR,
    elements_hash VARCHAR,
    created_at DateTime,
    array_property_keys Array(VARCHAR),
    array_property_values Array(VARCHAR)
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (team_id, created_at, id)
SAMPLE BY id
"""

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
arrayMap(k -> k.1, JSONExtractKeysAndValues(properties, 'varchar')) array_property_keys,
arrayMap(k -> k.2, JSONExtractKeysAndValues(properties, 'varchar')) array_property_values
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
