from .clickhouse import STORAGE_POLICY, table_engine

DROP_PERSON_TABLE_SQL = """
DROP TABLE person
"""

DROP_PERSON_DISTINCT_ID_TABLE_SQL = """
DROP TABLE person_distinct_id
"""

PERSONS_TABLE_SQL = """
CREATE TABLE person
(
    id Int32,
    created_at datetime,
    team_id Int32,
    properties VARCHAR
) ENGINE = {engine} 
Order By (team_id, id)
{storage_policy}
""".format(
    engine=table_engine("person"), storage_policy=STORAGE_POLICY
)

GET_PERSON_SQL = """
SELECT * FROM person
"""

PERSONS_DISTINCT_ID_TABLE_SQL = """
CREATE TABLE person_distinct_id
(
    id Int32,
    distinct_id VARCHAR,
    person_id Int32,
    team_id Int32
) ENGINE = {engine} 
Order By (team_id, id)
{storage_policy}
""".format(
    engine=table_engine("person_distinct_id"), storage_policy=STORAGE_POLICY
)

GET_DISTINCT_IDS_SQL = """
SELECT * FROM person_distinct_id
"""

GET_DISTINCT_IDS_SQL_BY_ID = """
SELECT * FROM person_distinct_id WHERE team_id = %(team_id)s AND person_id = %(person_id)s
"""

GET_PERSON_BY_DISTINCT_ID = """
SELECT p.id FROM person as p inner join person_distinct_id as pid on p.id = pid.person_id where team_id = %(team_id)s AND distinct_id = %(distinct_id)s
"""

PERSON_DISTINCT_ID_EXISTS_SQL = """
SELECT count(*) FROM person_distinct_id inner join (SELECT arrayJoin({}) as distinct_id) as id_params ON id_params.distinct_id = person_distinct_id.distinct_id where person_distinct_id.team_id = %(team_id)s
"""

PERSON_EXISTS_SQL = """
SELECT count(*) FROM person where id = %(id)s
"""

INSERT_PERSON_SQL = """
INSERT INTO person SELECT %(id)s, now(), %(team_id)s, %(properties)s
"""

INSERT_PERSON_DISTINCT_ID = """
INSERT INTO person_distinct_id SELECT generateUUIDv4(), %(distinct_id)s, %(person_id)s, %(team_id)s VALUES
"""

UPDATE_PERSON_PROPERTIES = """
ALTER TABLE person UPDATE properties = %(properties)s where id = %(id)s
"""

UPDATE_PERSON_ATTACHED_DISTINCT_ID = """
ALTER TABLE person_distinct_id UPDATE person_id = %(person_id)s where distinct_id = %(distinct_id)s
"""

DELETE_PERSON_BY_ID = """
ALTER TABLE person DELETE where id = %(id)s
"""
