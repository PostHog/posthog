PERSONS_TABLE_SQL = """
CREATE TABLE person
(
    id UUID,
    created_at datetime,
    properties varchar,
    team_id Int32
) ENGINE = MergeTree()
Order By (id)
"""

PERSONS_DISTINCT_ID_TABLE_SQL = """
CREATE TABLE person_distinct_id
(
    id UUID,
    distinct_id VARCHAR,
    person_id UUID,
    team_id Int32
) ENGINE = MergeTree()
Order By (id)
"""

PERSON_DISTINCT_ID_EXISTS_SQL = """
SELECT count(*) FROM person_distinct_id inner join (SELECT arrayJoin({}) as distinct_id) as something ON something.distinct_id = person_distinct_id.distinct_id
"""

INSERT_PERSON_SQL = """
INSERT INTO person SELECT '{id}', now(), '{properties}', {team_id}
"""

INSERT_PERSON_DISTINCT_ID = """
INSERT INTO person_distinct_id SELECT generateUUIDv4(), '{distinct_id}', '{person_id}', {team_id}
"""
