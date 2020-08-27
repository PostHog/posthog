DROP_ELEMENTS_TABLE_SQL = """
DROP TABLE elements
"""

DROP_ELEMENTS_GROUP_TABLE_SQL = """
DROP TABLE elements_group
"""


ELEMENTS_TABLE_SQL = """
CREATE TABLE elements
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
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(created_at)
ORDER BY (id, intHash32(team_id))
"""

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

ELEMENT_GROUP_TABLE_SQL = """
CREATE TABLE elements_group
(
    id UUID,
    elements_hash VARCHAR,
    team_id Int32
) ENGINE = MergeTree()
ORDER BY (id)
"""


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
