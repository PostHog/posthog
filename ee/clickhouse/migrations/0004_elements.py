from django_clickhouse import migrations

ELEMENTS_SQL = """
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

ELEMENT_GROUP_SQL = """
CREATE TABLE elements_group
(
    id UUID,
    elements_hash VARCHAR,
    team_id Int32
) ENGINE = MergeTree()
ORDER BY (id)
"""

operations = [migrations.RunSQL(ELEMENTS_SQL), migrations.RunSQL(ELEMENT_GROUP_SQL)]
