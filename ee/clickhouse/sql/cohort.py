CALCULATE_COHORT_PEOPLE_SQL = """
SELECT distinct_id FROM person_distinct_id where person_id IN {query} AND team_id = %(team_id)s
"""

GET_LATEST_PERSON_SQL = """
(select id from (
    SELECT * FROM person JOIN (
        SELECT id, max(created_at) as created_at FROM person WHERE team_id = %(team_id)s GROUP BY id
    ) as person_max ON person.id = person_max.id AND person.created_at = person_max.created_at
    WHERE team_id = %(team_id)s
    {query}
))
"""
