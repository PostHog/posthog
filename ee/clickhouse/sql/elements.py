from ee.kafka.topics import KAFKA_ELEMENTS

from .clickhouse import KAFKA_COLUMNS, STORAGE_POLICY, kafka_engine, table_engine

DROP_ELEMENTS_TABLE_SQL = """
DROP TABLE elements
"""

DROP_ELEMENTS_GROUP_TABLE_SQL = """
DROP TABLE elements_group
"""

ELEMENTS_TABLE = "elements"

ELEMENTS_TABLE_BASE_SQL = """
CREATE TABLE {table_name}
(
    uuid UUID,
    event_uuid UUID,
    text VARCHAR,
    tag_name VARCHAR,
    href VARCHAR,
    attr_id VARCHAR,
    attr_class Array(VARCHAR),
    nth_child Int64,
    nth_of_type Int64,
    attributes VARCHAR,
    order Int64,
    team_id Int64,
    created_at DateTime64,
    elements_hash VARCHAR
    {extra_fields}
) ENGINE = {engine} 
"""

ELEMENTS_TABLE_SQL = (
    ELEMENTS_TABLE_BASE_SQL
    + """PARTITION BY toYYYYMM(created_at)
ORDER BY (team_id, elements_hash, order)
{storage_policy}
"""
).format(
    table_name=ELEMENTS_TABLE,
    engine=table_engine(ELEMENTS_TABLE, "_timestamp"),
    extra_fields=KAFKA_COLUMNS,
    storage_policy=STORAGE_POLICY,
)

KAFKA_ELEMENTS_TABLE_SQL = ELEMENTS_TABLE_BASE_SQL.format(
    table_name="kafka_" + ELEMENTS_TABLE, engine=kafka_engine(topic=KAFKA_ELEMENTS), extra_fields=""
)

ELEMENTS_TABLE_MV_SQL = """
CREATE MATERIALIZED VIEW {table_name}_mv 
TO {table_name} 
AS SELECT
uuid,
event_uuid,
text,
tag_name,
href,
attr_id,
attr_class,
nth_child,
nth_of_type,
attributes,
order,
team_id,
created_at,
elements_hash,
_timestamp,
_offset
FROM kafka_{table_name} 
""".format(
    table_name=ELEMENTS_TABLE
)

INSERT_ELEMENTS_SQL = """
INSERT INTO elements SELECT 
    %(uuid)s,
    %(event_uuid)s, 
    %(text)s,
    %(tag_name)s,
    %(href)s,
    %(attr_id)s,
    %(attr_class)s,
    %(nth_child)s,
    %(nth_of_type)s,
    %(attributes)s,
    %(order)s,
    %(team_id)s,
    now(),
    %(elements_hash)s,
    now(), 
    0
"""

GET_ELEMENTS_BY_ELEMENTS_HASH_SQL = """
    SELECT 
        argMax(uuid, _timestamp) uuid,
        any(event_uuid) event_uuid, 
        any(text) text,
        any(tag_name) tag_name,
        any(href) href,
        any(attr_id) attr_id,
        any(attr_class) attr_class,
        any(nth_child) nth_child,
        any(nth_of_type) nth_of_type,
        any(attributes) attributes,
        order,
        team_id,
        max(_timestamp) _timestamp_,
        elements_hash,
        now(),
        0
    FROM elements
    WHERE elements_hash = %(elements_hash)s AND team_id=%(team_id)s
    GROUP BY team_id, elements_hash, order
    ORDER BY order
"""

GET_ALL_ELEMENTS_SQL = """
SELECT * FROM elements {final} ORDER by order ASC 
"""

ELEMENTS_WITH_ARRAY_PROPS = """
CREATE TABLE elements_with_array_props_view
(
    uuid UUID,
    event_uuid UUID,
    text VARCHAR,
    tag_name VARCHAR,
    href VARCHAR,
    attr_id VARCHAR,
    attr_class Array(VARCHAR),
    nth_child Int64,
    nth_of_type Int64,
    attributes VARCHAR,
    order Int64,
    team_id Int64,
    created_at DateTime64,
    elements_hash VARCHAR,
    array_attribute_keys Array(VARCHAR),
    array_attribute_values Array(VARCHAR),
    _timestamp UInt64,
    _offset UInt64
) ENGINE = {engine}
PARTITION BY toYYYYMM(created_at)
ORDER BY (team_id, elements_hash, order)
{storage_policy}
""".format(
    engine=table_engine("elements_with_array_props_view", "_timestamp"), storage_policy=STORAGE_POLICY
)

ELEMENTS_WITH_ARRAY_PROPS_MAT = """
CREATE MATERIALIZED VIEW elements_with_array_props_mv
TO elements_with_array_props_view
AS SELECT
uuid,
event_uuid,
text,
tag_name,
href,
attr_id,
attr_class,
nth_child,
nth_of_type,
attributes,
order,
team_id,
elements_hash,
arrayMap(k -> k.1, JSONExtractKeysAndValues(attributes, 'varchar')) array_attribute_keys,
arrayMap(k -> k.2, JSONExtractKeysAndValues(attributes, 'varchar')) array_attribute_values,
_timestamp,
_offset
FROM elements
"""

ELEMENTS_PROPERTIES_MAT = """
CREATE MATERIALIZED VIEW elements_properties_view
ENGINE = MergeTree()
ORDER BY (key, value, uuid)
POPULATE
AS SELECT uuid,
event_uuid,
team_id,
array_attribute_keys as key,
array_attribute_values as value
from elements_with_array_props_view
ARRAY JOIN array_attribute_keys, array_attribute_values
"""
