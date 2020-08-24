from django_clickhouse import migrations

PERSON_SQL = """
CREATE TABLE default.person
(
    id UUID,
    created_at datetime,
    properties varchar,
    team_id Int32,
    is_user_id Int32
) ENGINE = MergeTree()
Order By (id)
"""

PERSON_DISTINCT_ID_SQL = """
CREATE TABLE default.person_distinct_id
(
    id UUID,
    distinct_id UUID,
    person_id UUID,
    team_id Int32
) ENGINE = MergeTree()
Order By (id)
"""


operations = [migrations.RunSQL(PERSON_SQL), migrations.RunSQL(PERSON_DISTINCT_ID_SQL)]
