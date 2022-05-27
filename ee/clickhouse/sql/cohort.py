from ee.clickhouse.sql.person import PERSON_STATIC_COHORT_TABLE
from ee.clickhouse.sql.table_engines import CollapsingMergeTree
from posthog.settings import CLICKHOUSE_CLUSTER

CALCULATE_COHORT_PEOPLE_SQL = """
SELECT {id_column} FROM ({GET_TEAM_PERSON_DISTINCT_IDS}) WHERE {query}
"""

COHORTPEOPLE_TABLE_ENGINE = lambda: CollapsingMergeTree("cohortpeople", ver="sign")
CREATE_COHORTPEOPLE_TABLE_SQL = lambda: """
CREATE TABLE IF NOT EXISTS cohortpeople ON CLUSTER '{cluster}'
(
    person_id UUID,
    cohort_id Int64,
    team_id Int64,
    sign Int8
) ENGINE = {engine}
Order By (team_id, cohort_id, person_id)
{storage_policy}
""".format(
    cluster=CLICKHOUSE_CLUSTER, engine=COHORTPEOPLE_TABLE_ENGINE(), storage_policy="",
)

TRUNCATE_COHORTPEOPLE_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS cohortpeople ON CLUSTER '{CLICKHOUSE_CLUSTER}'"
DROP_COHORTPEOPLE_TABLE_SQL = f"DROP TABLE IF EXISTS cohortpeople ON CLUSTER '{CLICKHOUSE_CLUSTER}'"

REMOVE_PEOPLE_NOT_MATCHING_COHORT_ID_SQL = """
INSERT INTO cohortpeople
SELECT person_id, cohort_id, %(team_id)s as team_id,  -1 as _sign
FROM cohortpeople
JOIN (
    SELECT id, argMax(properties, person._timestamp) as properties, sum(is_deleted) as is_deleted FROM person WHERE team_id = %(team_id)s GROUP BY id
) as person ON (person.id = cohortpeople.person_id)
WHERE cohort_id = %(cohort_id)s
AND
    (
        person.is_deleted = 1 OR NOT person_id IN ({cohort_filter})
    )
"""

GET_COHORT_SIZE_SQL = """
SELECT count(*)
FROM (
    SELECT 1
    FROM cohortpeople
    WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s
    GROUP BY person_id, cohort_id, team_id
    HAVING sum(sign) > 0
)
"""

INSERT_PEOPLE_MATCHING_COHORT_ID_SQL = """
INSERT INTO cohortpeople
    SELECT id, %(cohort_id)s as cohort_id, %(team_id)s as team_id, 1 as _sign
    FROM (
        SELECT id, argMax(properties, person._timestamp) as properties, sum(is_deleted) as is_deleted FROM person WHERE team_id = %(team_id)s GROUP BY id
    ) as person
    LEFT JOIN (
        SELECT person_id, sum(sign) AS sign FROM cohortpeople WHERE cohort_id = %(cohort_id)s AND team_id = %(team_id)s GROUP BY person_id
    ) as cohortpeople ON (person.id = cohortpeople.person_id)
    WHERE (cohortpeople.person_id = '00000000-0000-0000-0000-000000000000' OR sign = 0)
    AND person.is_deleted = 0
    AND id IN ({cohort_filter})
"""

GET_DISTINCT_ID_BY_ENTITY_SQL = """
SELECT distinct_id FROM events WHERE team_id = %(team_id)s {date_query} AND {entity_query}
"""

GET_PERSON_ID_BY_ENTITY_COUNT_SQL = """
SELECT pdi.person_id as person_id FROM events
INNER JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) as pdi
ON events.distinct_id = pdi.distinct_id
WHERE team_id = %(team_id)s {date_query} AND {entity_query}
GROUP BY person_id {count_condition}
"""

GET_PERSON_ID_BY_PRECALCULATED_COHORT_ID = """
SELECT person_id FROM cohortpeople WHERE team_id = %(team_id)s AND cohort_id = %({prepend}_cohort_id_{index})s GROUP BY person_id, cohort_id, team_id HAVING sum(sign) > 0
"""

GET_COHORTS_BY_PERSON_UUID = """
SELECT cohort_id
FROM cohortpeople
WHERE team_id = %(team_id)s AND person_id = %(person_id)s
GROUP BY person_id, cohort_id, team_id
HAVING sum(sign) > 0
"""

GET_STATIC_COHORTPEOPLE_BY_PERSON_UUID = f"""
SELECT DISTINCT cohort_id
FROM {PERSON_STATIC_COHORT_TABLE}
WHERE team_id = %(team_id)s AND person_id = %(person_id)s
"""

GET_COHORTPEOPLE_BY_COHORT_ID = """
SELECT person_id
FROM cohortpeople
WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s
GROUP BY person_id, cohort_id, team_id
HAVING sum(sign) > 0
ORDER BY person_id
"""

GET_STATIC_COHORTPEOPLE_BY_COHORT_ID = f"""
SELECT person_id
FROM {PERSON_STATIC_COHORT_TABLE}
WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s
GROUP BY person_id, cohort_id, team_id
"""
