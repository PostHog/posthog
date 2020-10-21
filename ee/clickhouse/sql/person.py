from ee.kafka.topics import KAFKA_OMNI_PERSON, KAFKA_PERSON, KAFKA_PERSON_UNIQUE_ID

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
    table_name="kafka_" + PERSONS_TABLE, engine=kafka_engine(KAFKA_PERSON), extra_fields=""
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
    ts DateTime64
    {extra_fields}
) ENGINE = {engine} 
"""

OMNI_PERSONS_TABLE_SQL = (
    OMNI_PERSONS_TABLE_BASE_SQL
    + """Order By (team_id, uuid, distinct_id)
{storage_policy}
"""
).format(
    table_name=OMNI_PERSONS_TABLE,
    engine=table_engine(OMNI_PERSONS_TABLE, "_timestamp"),
    extra_fields=KAFKA_COLUMNS,
    storage_policy=STORAGE_POLICY,
)

KAFKA_OMNI_PERSONS_TABLE_SQL = OMNI_PERSONS_TABLE_BASE_SQL.format(
    table_name="kafka_" + OMNI_PERSONS_TABLE, engine=kafka_engine(KAFKA_OMNI_PERSON), extra_fields=""
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
    table_name="kafka_" + PERSONS_DISTINCT_ID_TABLE, engine=kafka_engine(KAFKA_PERSON_UNIQUE_ID), extra_fields=""
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

PERSON_TREND_SQL = """
SELECT DISTINCT distinct_id FROM events WHERE team_id = %(team_id)s {entity_filter} {filters} {parsed_date_from} {parsed_date_to}
"""

PEOPLE_THROUGH_DISTINCT_SQL = """
SELECT id, created_at, team_id, properties, is_identified, groupArray(distinct_id) FROM person INNER JOIN (
    SELECT DISTINCT person_id, distinct_id FROM person_distinct_id WHERE distinct_id IN ({content_sql})
) as pdi ON person.id = pdi.person_id GROUP BY id, created_at, team_id, properties, is_identified
LIMIT 200 OFFSET %(offset)s
"""

PEOPLE_SQL = """
SELECT id, created_at, team_id, properties, is_identified, groupArray(distinct_id) FROM person INNER JOIN (
    SELECT DISTINCT person_id, distinct_id FROM person_distinct_id WHERE person_id IN ({content_sql})
) as pdi ON person.id = pdi.person_id GROUP BY id, created_at, team_id, properties, is_identified
LIMIT 200 OFFSET %(offset)s 
"""

PEOPLE_BY_TEAM_SQL = """
SELECT id, created_at, team_id, properties, is_identified, groupArray(distinct_id) FROM person INNER JOIN (
    SELECT DISTINCT person_id, distinct_id FROM person_distinct_id WHERE team_id = %(team_id)s
) as pdi ON person.id = pdi.person_id 
WHERE team_id = %(team_id)s {filters} 
GROUP BY id, created_at, team_id, properties, is_identified
LIMIT 100 OFFSET %(offset)s 
"""

GET_PERSON_TOP_PROPERTIES = """
SELECT key, count(1) as count FROM (
    SELECT 
    array_property_keys as key,
    array_property_values as value
    from (
        SELECT
            arrayMap(k -> toString(k.1), JSONExtractKeysAndValuesRaw(properties)) AS array_property_keys,
            arrayMap(k -> toString(k.2), JSONExtractKeysAndValuesRaw(properties)) AS array_property_values
        FROM person WHERE team_id = %(team_id)s
    )
    ARRAY JOIN array_property_keys, array_property_values
) GROUP BY key ORDER BY count DESC LIMIT %(limit)s
"""


GET_DISTINCT_IDS_BY_PROPERTY_SQL = """
SELECT distinct_id FROM person_distinct_id WHERE person_id {negation}IN 
(
    SELECT id FROM (
        SELECT
        id, 
        array_property_keys as key,
        array_property_values as value
        from (
            SELECT
                id,
                arrayMap(k -> toString(k.1), JSONExtractKeysAndValuesRaw(properties)) AS array_property_keys,
                arrayMap(k -> toString(k.2), JSONExtractKeysAndValuesRaw(properties)) AS array_property_values
            FROM person WHERE team_id = %(team_id)s
        )
        ARRAY JOIN array_property_keys, array_property_values
    ) ep
    WHERE {filters}
) AND team_id = %(team_id)s
"""
