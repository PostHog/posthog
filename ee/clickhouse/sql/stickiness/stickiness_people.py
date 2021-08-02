STICKINESS_PEOPLE_SQL = """
SELECT DISTINCT pdi FROM (
    SELECT DISTINCT person_distinct_id.person_id AS pdi, countDistinct({trunc_func}(toDateTime(timestamp))) AS num_intervals
    FROM events
    LEFT JOIN ({GET_TEAM_PERSON_DISTINCT_IDS}) AS person_distinct_id ON person_distinct_id.distinct_id = events.distinct_id
    WHERE team_id = %(team_id)s {entity_filter} {filters} {parsed_date_from} {parsed_date_to}
    GROUP BY person_distinct_id.person_id
) WHERE num_intervals = %(stickiness_day)s
"""
