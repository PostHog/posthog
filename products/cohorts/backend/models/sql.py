from posthog.models.person.sql import PERSON_STATIC_COHORT_TABLE

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
