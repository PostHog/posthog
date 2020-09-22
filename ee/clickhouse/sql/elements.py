from ee.kafka.topics import KAFKA_ELEMENTS, KAFKA_ELEMENTS_GROUP

from .clickhouse import STORAGE_POLICY, kafka_engine, table_engine

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
    id UUID,
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
    created_at DateTime,
    group_id UUID,
    _timestamp UInt64,
    _offset UInt64
) ENGINE = {engine} 
"""

ELEMENTS_TABLE_SQL = (
    ELEMENTS_TABLE_BASE_SQL
    + """PARTITION BY toYYYYMM(created_at)
ORDER BY (team_id, group_id, id)
{storage_policy}
"""
).format(table_name=ELEMENTS_TABLE, engine=table_engine(ELEMENTS_TABLE, "_timestamp"), storage_policy=STORAGE_POLICY)

KAFKA_ELEMENTS_TABLE_SQL = ELEMENTS_TABLE_BASE_SQL.format(
    table_name="kafka_" + ELEMENTS_TABLE, engine=kafka_engine(topic=KAFKA_ELEMENTS)
)

ELEMENTS_TABLE_MV_SQL = """
CREATE MATERIALIZED VIEW {table_name}_mv 
TO {table_name} 
AS SELECT
id,
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
group_id,
_timestamp,
_offset
FROM kafka_{table_name} 
""".format(
    table_name=ELEMENTS_TABLE
)

INSERT_ELEMENTS_SQL = """
INSERT INTO elements SELECT 
    generateUUIDv4(), 
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
    %(group_id)s
"""

ELEMENTS_GROUP_TABLE = "elements_group"

ELEMENTS_GROUP_TABLE_BASE_SQL = """
CREATE TABLE {table_name} 
(
    id UUID,
    elements_hash VARCHAR,
    team_id Int64,
    _timestamp UInt64,
    _offset UInt64
) ENGINE = {engine}
"""

ELEMENTS_GROUP_TABLE_SQL = (
    ELEMENTS_GROUP_TABLE_BASE_SQL
    + """
    ORDER BY (team_id, elements_hash, id)
{storage_policy}
"""
).format(
    table_name=ELEMENTS_GROUP_TABLE,
    engine=table_engine(ELEMENTS_GROUP_TABLE, "_timestamp"),
    storage_policy=STORAGE_POLICY,
)

KAFKA_ELEMENTS_GROUP_TABLE_SQL = ELEMENTS_GROUP_TABLE_BASE_SQL.format(
    table_name="kafka_" + ELEMENTS_GROUP_TABLE, engine=kafka_engine(KAFKA_ELEMENTS_GROUP)
)

ELEMENTS_GROUP_TABLE_MV_SQL = """
CREATE MATERIALIZED VIEW {table_name}_mv 
TO {table_name} 
AS SELECT
id,
elements_hash,
team_id,
_timestamp,
_offset
FROM kafka_{table_name} 
""".format(
    table_name=ELEMENTS_GROUP_TABLE
)

INSERT_ELEMENT_GROUP_SQL = """
INSERT INTO elements_group SELECT %(id)s, %(element_hash)s, %(team_id)s
"""

GET_ELEMENT_GROUP_BY_HASH_SQL = """
SELECT * FROM elements_group where elements_hash = %(elements_hash)s
"""

GET_ELEMENT_BY_GROUP_SQL = """
SELECT * FROM elements where group_id = %(group_id)s order by order ASC
"""

GET_ELEMENTS_SQL = """
SELECT * FROM elements order by order ASC
"""

ELEMENTS_WITH_ARRAY_PROPS = """
CREATE TABLE elements_with_array_props_view
(
    id UUID,
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
    created_at DateTime,
    group_id UUID,
    array_attribute_keys Array(VARCHAR),
    array_attribute_values Array(VARCHAR),
    _timestamp UInt64,
    _offset UInt64
) ENGINE = {engine}
PARTITION BY toYYYYMM(created_at)
ORDER BY (team_id, group_id, id)
{storage_policy}
""".format(
    engine=table_engine("elements_with_array_props_view", "_timestamp"), storage_policy=STORAGE_POLICY
)

ELEMENTS_WITH_ARRAY_PROPS_MAT = """
CREATE MATERIALIZED VIEW elements_with_array_props_mv
TO elements_with_array_props_view
AS SELECT
id,
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
group_id,
arrayMap(k -> k.1, JSONExtractKeysAndValues(attributes, 'varchar')) array_attribute_keys,
arrayMap(k -> k.2, JSONExtractKeysAndValues(attributes, 'varchar')) array_attribute_values,
_timestamp,
_offset
FROM elements
"""

ELEMENTS_PROPERTIES_MAT = """
CREATE MATERIALIZED VIEW elements_properties_view
ENGINE = MergeTree()
ORDER BY (key, value, id)
POPULATE
AS SELECT id,
team_id,
array_attribute_keys as key,
array_attribute_values as value
from elements_with_array_props_view
ARRAY JOIN array_attribute_keys, array_attribute_values
"""
