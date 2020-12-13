STICKINESS_PEOPLE_SQL = """
SELECT DISTINCT pid FROM (
    SELECT DISTINCT person_distinct_id.person_id as pid, countDistinct({trunc_func}(toDateTime(timestamp))) as num_intervals
    FROM events
    LEFT JOIN (SELECT person_id, distinct_id FROM person_distinct_id WHERE team_id = %(team_id)s) as person_distinct_id ON person_distinct_id.distinct_id = events.distinct_id
    WHERE team_id = %(team_id)s {entity_filter} {filters} {parsed_date_from} {parsed_date_to}
    GROUP BY person_distinct_id.person_id
) WHERE num_intervals = %(stickiness_day)s
"""
