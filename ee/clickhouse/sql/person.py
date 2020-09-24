from ee.kafka.topics import KAFKA_OMNI_PERSON, KAFKA_PERSON, KAFKA_PERSON_UNIQUE_ID

from .clickhouse import STORAGE_POLICY, kafka_engine, table_engine

DROP_PERSON_TABLE_SQL = """
DROP TABLE person
"""

DROP_PERSON_DISTINCT_ID_TABLE_SQL = """
DROP TABLE person_distinct_id
"""

PERSONS_TABLE = "person"

PERSONS_TABLE_BASE_SQL = """
CREATE TABLE {table_name} 
(
    id UUID,
    created_at datetime,
    team_id Int64,
    properties VARCHAR,
    is_identified Boolean,
    _timestamp UInt64,
    _offset UInt64
) ENGINE = {engine} 
"""

PERSONS_TABLE_SQL = (
    PERSONS_TABLE_BASE_SQL
    + """Order By (team_id, id)
{storage_policy}
"""
).format(table_name=PERSONS_TABLE, engine=table_engine(PERSONS_TABLE, "_timestamp"), storage_policy=STORAGE_POLICY)

KAFKA_PERSONS_TABLE_SQL = PERSONS_TABLE_BASE_SQL.format(
    table_name="kafka_" + PERSONS_TABLE, engine=kafka_engine(KAFKA_PERSON)
)

PERSONS_TABLE_MV_SQL = """
CREATE MATERIALIZED VIEW {table_name}_mv 
TO {table_name} 
AS SELECT
id,
created_at,
team_id,
properties,
is_identified,
_timestamp,
_offset
FROM kafka_{table_name} 
""".format(
    table_name=PERSONS_TABLE
)


OMNI_PERSONS_TABLE = "omni_person"

OMNI_PERSONS_TABLE_BASE_SQL = """
CREATE TABLE {table_name} 
(
    uuid UUID,
    event_uuid UUID,
    team_id Int64,
    distinct_id VARCHAR,
    properties VARCHAR,
    is_identified Boolean,
    ts DateTime, 
    _timestamp UInt64,
    _offset UInt64
) ENGINE = {engine} 
"""

OMNI_PERSONS_TABLE_SQL = (
    OMNI_PERSONS_TABLE_BASE_SQL
    + """Order By (team_id, uuid, distinct_id)
{storage_policy}
"""
).format(
    table_name=OMNI_PERSONS_TABLE, engine=table_engine(OMNI_PERSONS_TABLE, "_timestamp"), storage_policy=STORAGE_POLICY
)

KAFKA_OMNI_PERSONS_TABLE_SQL = OMNI_PERSONS_TABLE_BASE_SQL.format(
    table_name="kafka_" + OMNI_PERSONS_TABLE, engine=kafka_engine(KAFKA_OMNI_PERSON)
)

OMNI_PERSONS_TABLE_MV_SQL = """
CREATE MATERIALIZED VIEW {table_name}_mv 
TO {table_name} 
AS SELECT
uuid,
event_uuid,
team_id,
distinct_id,
properties,
is_identified,
ts,
_timestamp,
_offset
FROM kafka_{table_name} 
""".format(
    table_name=OMNI_PERSONS_TABLE
)


GET_PERSON_SQL = """
SELECT * FROM person WHERE team_id = %(team_id)s
"""

PERSONS_DISTINCT_ID_TABLE = "person_distinct_id"

PERSONS_DISTINCT_ID_TABLE_BASE_SQL = """
CREATE TABLE {table_name} 
(
    id Int64,
    distinct_id VARCHAR,
    person_id UUID,
    team_id Int64,
    _timestamp UInt64,
    _offset UInt64
) ENGINE = {engine} 
"""

PERSONS_DISTINCT_ID_TABLE_SQL = (
    PERSONS_DISTINCT_ID_TABLE_BASE_SQL
    + """Order By (team_id, distinct_id, person_id, id)
{storage_policy}
"""
).format(
    table_name=PERSONS_DISTINCT_ID_TABLE,
    engine=table_engine(PERSONS_DISTINCT_ID_TABLE, "_timestamp"),
    storage_policy=STORAGE_POLICY,
)

KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL = PERSONS_DISTINCT_ID_TABLE_BASE_SQL.format(
    table_name="kafka_" + PERSONS_DISTINCT_ID_TABLE, engine=kafka_engine(KAFKA_PERSON_UNIQUE_ID)
)

PERSONS_DISTINCT_ID_TABLE_MV_SQL = """
CREATE MATERIALIZED VIEW {table_name}_mv 
TO {table_name} 
AS SELECT
id,
distinct_id,
person_id,
team_id,
_timestamp,
_offset
FROM kafka_{table_name} 
""".format(
    table_name=PERSONS_DISTINCT_ID_TABLE
)

GET_DISTINCT_IDS_SQL = """
SELECT * FROM person_distinct_id WHERE team_id = %(team_id)s
"""

GET_DISTINCT_IDS_SQL_BY_ID = """
SELECT * FROM person_distinct_id WHERE team_id = %(team_id)s AND person_id = %(person_id)s
"""

GET_PERSON_BY_DISTINCT_ID = """
SELECT p.* FROM person as p inner join person_distinct_id as pid on p.id = pid.person_id where team_id = %(team_id)s AND distinct_id = %(distinct_id)s
"""

PERSON_DISTINCT_ID_EXISTS_SQL = """
SELECT count(*) FROM person_distinct_id
inner join (
    SELECT arrayJoin({}) as distinct_id
    ) as id_params ON id_params.distinct_id = person_distinct_id.distinct_id
where person_distinct_id.team_id = %(team_id)s
"""

PERSON_EXISTS_SQL = """
SELECT count(*) FROM person where id = %(id)s
"""

INSERT_PERSON_SQL = """
INSERT INTO person SELECT %(id)s, now(), %(team_id)s, %(properties)s, %(is_identified)s, now(), 0
"""

INSERT_PERSON_DISTINCT_ID = """
INSERT INTO person_distinct_id SELECT %(id)s, %(distinct_id)s, %(person_id)s, %(team_id)s, now(), 0 VALUES
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

DELETE_PERSON_DISTINCT_ID_BY_PERSON_ID = """
ALTER TABLE person_distinct_id DELETE where person_id = %(id)s
"""

UPDATE_PERSON_IS_IDENTIFIED = """
ALTER TABLE person UPDATE is_identified = %(is_identified)s where id = %(id)s
"""
