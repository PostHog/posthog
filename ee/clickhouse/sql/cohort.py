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
    sign Int8,
    version UInt64
) ENGINE = {engine}
Order By (team_id, cohort_id, person_id, version)
{storage_policy}
""".format(
    cluster=CLICKHOUSE_CLUSTER, engine=COHORTPEOPLE_TABLE_ENGINE(), storage_policy="",
)

TRUNCATE_COHORTPEOPLE_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS cohortpeople ON CLUSTER '{CLICKHOUSE_CLUSTER}'"

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

RECALCULATE_COHORT_BY_ID = """
INSERT INTO cohortpeople
SELECT id, %(cohort_id)s as cohort_id, %(team_id)s as team_id, 1 AS sign, %(new_version)s AS version
FROM (
    SELECT id, argMax(properties, person._timestamp) as properties, sum(is_deleted) as is_deleted FROM person WHERE team_id = %(team_id)s GROUP BY id
) as person
WHERE person.is_deleted = 0
AND id IN ({cohort_filter})
UNION ALL
SELECT person_id, cohort_id, team_id, -1, version
FROM cohortpeople
WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s AND version < %(new_version)s AND sign = 1
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
SELECT person_id FROM cohortpeople WHERE team_id = %(team_id)s AND cohort_id = %({prepend}_cohort_id_{index})s GROUP BY person_id, cohort_id, team_id, version HAVING sum(sign) > 0
"""

GET_COHORTS_BY_PERSON_UUID = """
SELECT DISTINCT cohort_id
FROM cohortpeople
WHERE team_id = %(team_id)s AND person_id = %(person_id)s
GROUP BY person_id, cohort_id, team_id, version
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
GROUP BY person_id, cohort_id, team_id, version
HAVING sum(sign) > 0
ORDER BY person_id
"""

GET_STATIC_COHORTPEOPLE_BY_COHORT_ID = f"""
SELECT person_id
FROM {PERSON_STATIC_COHORT_TABLE}
WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s
GROUP BY person_id, cohort_id, team_id
"""
