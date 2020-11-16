CALCULATE_COHORT_PEOPLE_SQL = """
SELECT distinct_id FROM person_distinct_id where {query} AND team_id = %(team_id)s
"""
