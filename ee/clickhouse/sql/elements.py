from ee.kafka.topics import KAFKA_ELEMENTS, KAFKA_ELEMENTS_GROUP

from .clickhouse import STORAGE_POLICY, kafka_engine, table_engine

DROP_ELEMENTS_TABLE_SQL = """
DROP TABLE elements
"""

DROP_ELEMENTS_GROUP_TABLE_SQL = """
DROP TABLE elements_group
"""


ELEMENTS_TABLE_BASE_SQL = """
CREATE TABLE {table_name} 
(
    id UUID,
    text VARCHAR,
    tag_name VARCHAR,
    href VARCHAR,
    attr_id VARCHAR,
    attr_class Array(VARCHAR),
    nth_child Int32,
    nth_of_type Int32,
    attributes VARCHAR,
    order Int32,
    team_id Int32,
    created_at DateTime,
    group_id UUID
) ENGINE = {engine} 
"""

ELEMENTS_TABLE_SQL = (
    ELEMENTS_TABLE_BASE_SQL
    + """PARTITION BY toYYYYMM(created_at)
ORDER BY (team_id, id)
{storage_policy}
"""
).format(table_name="elements", engine=table_engine("elements"), storage_policy=STORAGE_POLICY)

KAFKA_ELEMENTS_TABLE_SQL = ELEMENTS_TABLE_BASE_SQL.format(
    table_name="kafka_elements", engine=kafka_engine(topic=KAFKA_ELEMENTS)
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

ELEMENT_GROUP_TABLE_BASE_SQL = """
CREATE TABLE {table_name} 
(
    id UUID,
    elements_hash VARCHAR,
    team_id Int32
) ENGINE = {engine}
"""

ELEMENT_GROUP_TABLE_SQL = (
    ELEMENTS_TABLE_BASE_SQL
    + """ORDER BY (team_id, id)
{storage_policy}
"""
).format(table_name="elements_group", engine=table_engine("elements_group"), storage_policy=STORAGE_POLICY)

KAFKA_ELEMENTS_GROUP_TABLE_SQL = ELEMENTS_TABLE_BASE_SQL.format(
    table_name="kafka_elements_group", engine=kafka_engine(KAFKA_ELEMENTS_GROUP)
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
    nth_child Int32,
    nth_of_type Int32,
    attributes VARCHAR,
    order Int32,
    team_id Int32,
    created_at DateTime,
    group_id UUID,
    array_attribute_keys Array(VARCHAR),
    array_attribute_values Array(VARCHAR)
) ENGINE = {engine}
PARTITION BY toYYYYMM(created_at)
ORDER BY (id, team_id)
{storage_policy}
""".format(
    engine=table_engine("elements_with_array_props_view"), storage_policy=STORAGE_POLICY
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
arrayMap(k -> k.2, JSONExtractKeysAndValues(attributes, 'varchar')) array_attribute_values
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
