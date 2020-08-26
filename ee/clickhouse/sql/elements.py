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
    '{text}',
    '{tag_name}',
    '{href}',
    '{attr_id}',
    {attr_class},
    {nth_child},
    {nth_of_type},
    '{attributes}',
    {order},
    {team_id},
    now(),
    '{group_id}'
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
INSERT INTO elements_group SELECT '{id}', '{element_hash}', {team_id}
"""
