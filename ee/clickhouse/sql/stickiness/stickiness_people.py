STICKINESS_PEOPLE_SQL = """
SELECT DISTINCT pid FROM (
    SELECT DISTINCT person_distinct_id.person_id as pid, countDistinct(toDate(timestamp)) as day_count
    FROM events
    LEFT JOIN person_distinct_id ON person_distinct_id.distinct_id = events.distinct_id
    WHERE team_id = %(team_id)s {entity_filter} {filters} {parsed_date_from} {parsed_date_to}
    GROUP BY person_distinct_id.person_id
) WHERE day_count = %(stickiness_day)s
"""
