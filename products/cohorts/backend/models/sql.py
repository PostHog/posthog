from posthog.clickhouse.cluster import ON_CLUSTER_CLAUSE
from posthog.clickhouse.table_engines import CollapsingMergeTree
from posthog.models.person.sql import PERSON_STATIC_COHORT_TABLE
from posthog.settings import CLICKHOUSE_CLUSTER

CALCULATE_COHORT_PEOPLE_SQL = """
SELECT {id_column} FROM ({GET_TEAM_PERSON_DISTINCT_IDS}) WHERE {query}
"""


def COHORTPEOPLE_TABLE_ENGINE():
    return CollapsingMergeTree("cohortpeople", ver="sign")


CREATE_COHORTPEOPLE_TABLE_SQL = (
    lambda on_cluster=True: """
CREATE TABLE IF NOT EXISTS cohortpeople {on_cluster_clause}
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
        on_cluster_clause=ON_CLUSTER_CLAUSE(on_cluster),
        engine=COHORTPEOPLE_TABLE_ENGINE(),
        storage_policy="",
    )
)

TRUNCATE_COHORTPEOPLE_TABLE_SQL = f"TRUNCATE TABLE IF EXISTS cohortpeople ON CLUSTER '{CLICKHOUSE_CLUSTER}'"

GET_COHORT_SIZE_SQL = """
SELECT count(DISTINCT person_id)
FROM cohortpeople
WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s AND version = %(version)s
"""

# Continually ensure that all previous version rows are deleted and insert persons that match the criteria
# optimize_aggregation_in_order = 1 is necessary to avoid oom'ing for our biggest clients
RECALCULATE_COHORT_BY_ID = """
INSERT INTO cohortpeople
SELECT id, %(cohort_id)s as cohort_id, %(team_id)s as team_id, 1 AS sign, %(new_version)s AS version
FROM (
    {cohort_filter}
) as person
SETTINGS optimize_aggregation_in_order = 1, join_algorithm = 'auto'
"""

# NOTE: Group by version id to ensure that signs are summed between corresponding rows.
# Version filtering is not necessary as only positive rows of the latest version will be selected by sum(sign) > 0

GET_PERSON_ID_BY_PRECALCULATED_COHORT_ID = """
SELECT DISTINCT person_id FROM cohortpeople WHERE team_id = %(team_id)s AND cohort_id = %({prepend}_cohort_id_{index})s AND version = %({prepend}_version_{index})s
"""

GET_COHORTS_BY_PERSON_UUID = """
SELECT cohort_id, argMax(version, version) as latest_version
  FROM cohortpeople
  WHERE team_id = %(team_id)s AND person_id = %(person_id)s
  GROUP BY cohort_id
  HAVING argMax(sign, version) > 0
"""

GET_STATIC_COHORTPEOPLE_BY_PERSON_UUID = f"""
SELECT DISTINCT cohort_id
FROM {PERSON_STATIC_COHORT_TABLE}
WHERE team_id = %(team_id)s AND person_id = %(person_id)s
"""

GET_COHORTPEOPLE_BY_COHORT_ID = """
SELECT DISTINCT person_id
FROM cohortpeople
WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s AND version = %(version)s
ORDER BY person_id
"""

GET_STATIC_COHORTPEOPLE_BY_COHORT_ID = f"""
SELECT person_id
FROM {PERSON_STATIC_COHORT_TABLE}
WHERE team_id = %(team_id)s AND cohort_id = %(cohort_id)s
GROUP BY person_id, cohort_id, team_id
"""


STALE_COHORTPEOPLE = f"""
SELECT team_id, count() AS stale_people_count FROM cohortpeople
WHERE team_id IN %(team_ids)s AND cohort_id = %(cohort_id)s AND version < %(version)s
GROUP BY team_id
HAVING stale_people_count > 0
"""
