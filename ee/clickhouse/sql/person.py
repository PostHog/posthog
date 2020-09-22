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
    id UUID,
    created_at datetime,
    team_id Int32,
    properties VARCHAR,
    is_identified Boolean
) ENGINE = {engine} 
Order By (team_id, id)
{storage_policy}
""".format(
    engine=table_engine("person"), storage_policy=STORAGE_POLICY
)

GET_PERSON_SQL = """
SELECT * FROM person WHERE team_id = %(team_id)s
"""

PERSONS_DISTINCT_ID_TABLE_SQL = """
CREATE TABLE person_distinct_id
(
    id Int32,
    distinct_id VARCHAR,
    person_id UUID,
    team_id Int32
) ENGINE = {engine} 
Order By (team_id, id)
{storage_policy}
""".format(
    engine=table_engine("person_distinct_id"), storage_policy=STORAGE_POLICY
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
SELECT count(*) FROM person_distinct_id inner join (SELECT arrayJoin({}) as distinct_id) as id_params ON id_params.distinct_id = person_distinct_id.distinct_id where person_distinct_id.team_id = %(team_id)s
"""

PERSON_EXISTS_SQL = """
SELECT count(*) FROM person where id = %(id)s
"""

INSERT_PERSON_SQL = """
INSERT INTO person SELECT %(id)s, now(), %(team_id)s, %(properties)s, 0
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
