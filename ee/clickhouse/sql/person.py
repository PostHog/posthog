from ee.kafka_client.topics import KAFKA_PERSON, KAFKA_PERSON_UNIQUE_ID

from .clickhouse import KAFKA_COLUMNS, STORAGE_POLICY, kafka_engine, table_engine

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
    created_at DateTime64,
    team_id Int64,
    properties VARCHAR,
    is_identified Boolean
    {extra_fields}
) ENGINE = {engine} 
"""

PERSONS_TABLE_SQL = (
    PERSONS_TABLE_BASE_SQL
    + """Order By (team_id, id)
{storage_policy}
"""
).format(
    table_name=PERSONS_TABLE,
    engine=table_engine(PERSONS_TABLE, "_timestamp"),
    extra_fields=KAFKA_COLUMNS,
    storage_policy=STORAGE_POLICY,
)

KAFKA_PERSONS_TABLE_SQL = PERSONS_TABLE_BASE_SQL.format(
    table_name="kafka_" + PERSONS_TABLE, engine=kafka_engine(KAFKA_PERSON), extra_fields="",
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

GET_LATEST_PERSON_SQL = """
SELECT * FROM person JOIN (
    SELECT id, max(created_at) as created_at FROM person WHERE team_id = %(team_id)s GROUP BY id
) as person_max ON person.id = person_max.id AND person.created_at = person_max.created_at
WHERE team_id = %(team_id)s
{query}
"""

GET_LATEST_PERSON_ID_SQL = """
(select id from (
    {latest_person_sql}
))
""".format(
    latest_person_sql=GET_LATEST_PERSON_SQL
)

GET_PERSON_SQL = """
SELECT * FROM ({latest_person_sql}) person WHERE team_id = %(team_id)s
""".format(
    latest_person_sql=GET_LATEST_PERSON_SQL
)

PERSONS_DISTINCT_ID_TABLE = "person_distinct_id"

PERSONS_DISTINCT_ID_TABLE_BASE_SQL = """
CREATE TABLE {table_name} 
(
    id Int64,
    distinct_id VARCHAR,
    person_id UUID,
    team_id Int64
    {extra_fields}
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
    extra_fields=KAFKA_COLUMNS,
    storage_policy=STORAGE_POLICY,
)

KAFKA_PERSONS_DISTINCT_ID_TABLE_SQL = PERSONS_DISTINCT_ID_TABLE_BASE_SQL.format(
    table_name="kafka_" + PERSONS_DISTINCT_ID_TABLE, engine=kafka_engine(KAFKA_PERSON_UNIQUE_ID), extra_fields="",
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

#
# Static Cohort
#

PERSON_STATIC_COHORT_TABLE = "person_static_cohort"
PERSON_STATIC_COHORT_BASE_SQL = """
CREATE TABLE {table_name} 
(
    id UUID,
    person_id UUID,
    cohort_id Int64,
    team_id Int64
    {extra_fields}
) ENGINE = {engine} 
"""

PERSON_STATIC_COHORT_TABLE_SQL = (
    PERSON_STATIC_COHORT_BASE_SQL
    + """Order By (team_id, cohort_id, person_id, id)
{storage_policy}
"""
).format(
    table_name=PERSON_STATIC_COHORT_TABLE,
    engine=table_engine(PERSON_STATIC_COHORT_TABLE, "_timestamp"),
    storage_policy=STORAGE_POLICY,
    extra_fields=KAFKA_COLUMNS,
)

DROP_PERSON_STATIC_COHORT_TABLE_SQL = """
DROP TABLE {}
""".format(
    PERSON_STATIC_COHORT_TABLE
)

INSERT_PERSON_STATIC_COHORT = """
INSERT INTO {} (id, person_id, cohort_id, team_id, _timestamp) VALUES 
""".format(
    PERSON_STATIC_COHORT_TABLE
)

#
# Other queries
#

GET_DISTINCT_IDS_SQL = """
SELECT * FROM person_distinct_id WHERE team_id = %(team_id)s
"""

GET_DISTINCT_IDS_SQL_BY_ID = """
SELECT * FROM person_distinct_id WHERE team_id = %(team_id)s AND person_id = %(person_id)s
"""

GET_PERSON_IDS_BY_FILTER = """
SELECT DISTINCT p.id
FROM ({latest_person_sql}) AS p
INNER JOIN (
    SELECT person_id, distinct_id
    FROM person_distinct_id
    WHERE team_id = %(team_id)s
) AS pid ON p.id = pid.person_id
WHERE team_id = %(team_id)s
  {distinct_query}
""".format(
    latest_person_sql=GET_LATEST_PERSON_SQL, distinct_query="{distinct_query}"
)

GET_PERSON_BY_DISTINCT_ID = """
SELECT p.id
FROM ({latest_person_sql}) AS p
INNER JOIN (
    SELECT person_id, distinct_id
    FROM person_distinct_id
    WHERE team_id = %(team_id)s
) AS pid ON p.id = pid.person_id
WHERE team_id = %(team_id)s
  AND pid.distinct_id = %(distinct_id)s
  {distinct_query}
""".format(
    latest_person_sql=GET_LATEST_PERSON_SQL, distinct_query="{distinct_query}"
)

GET_PERSONS_BY_DISTINCT_IDS = """
SELECT 
    p.id,
    p.created_at,
    p.team_id,
    p.properties,
    p.is_identified,
    groupArray(pid.distinct_id) as distinct_ids
FROM 
    person as p 
INNER JOIN 
    person_distinct_id as pid on p.id = pid.person_id 
WHERE 
    team_id = %(team_id)s 
    AND distinct_id IN (%(distinct_ids)s)
GROUP BY
    p.id,
    p.created_at,
    p.team_id,
    p.properties,
    p.is_identified
"""

PERSON_DISTINCT_ID_EXISTS_SQL = """
SELECT count(*) FROM person_distinct_id
inner join (
    SELECT arrayJoin({}) as distinct_id
    ) as id_params ON id_params.distinct_id = person_distinct_id.distinct_id
where person_distinct_id.team_id = %(team_id)s
"""

INSERT_PERSON_SQL = """
INSERT INTO person SELECT %(id)s, %(created_at)s, %(team_id)s, %(properties)s, %(is_identified)s, now(), 0
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

DELETE_PERSON_EVENTS_BY_ID = """
ALTER TABLE events DELETE
where distinct_id IN (
    SELECT distinct_id FROM person_distinct_id WHERE person_id=%(id)s AND team_id = %(team_id)s
)
AND team_id = %(team_id)s
"""

DELETE_PERSON_DISTINCT_ID_BY_PERSON_ID = """
ALTER TABLE person_distinct_id DELETE where person_id = %(id)s
"""

UPDATE_PERSON_IS_IDENTIFIED = """
ALTER TABLE person UPDATE is_identified = %(is_identified)s where id = %(id)s
"""

PERSON_TREND_SQL = """
SELECT DISTINCT distinct_id FROM events WHERE team_id = %(team_id)s {entity_filter} {filters} {parsed_date_from} {parsed_date_to} {person_filter}
"""

PEOPLE_THROUGH_DISTINCT_SQL = """
SELECT id, created_at, team_id, properties, is_identified, groupArray(distinct_id) FROM (
    {latest_person_sql}
) as person INNER JOIN (
    SELECT DISTINCT person_id, distinct_id FROM person_distinct_id WHERE distinct_id IN ({content_sql}) AND team_id = %(team_id)s
) as pdi ON person.id = pdi.person_id
WHERE team_id = %(team_id)s
GROUP BY id, created_at, team_id, properties, is_identified
LIMIT 200 OFFSET %(offset)s
"""

PEOPLE_SQL = """
SELECT id, created_at, team_id, properties, is_identified, groupArray(distinct_id) FROM (
    {latest_person_sql}
) as person INNER JOIN (
    SELECT DISTINCT person_id, distinct_id FROM person_distinct_id WHERE person_id IN ({content_sql}) AND team_id = %(team_id)s
) as pdi ON person.id = pdi.person_id GROUP BY id, created_at, team_id, properties, is_identified
LIMIT 100 OFFSET %(offset)s 
"""

GET_DISTINCT_IDS_BY_PROPERTY_SQL = """
SELECT distinct_id FROM person_distinct_id WHERE person_id IN
(
    SELECT id
    FROM person
    WHERE team_id = %(team_id)s {filters}
) AND team_id = %(team_id)s
"""
