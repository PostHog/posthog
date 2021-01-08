STICKINESS_ACTIONS_SQL = """
    SELECT countDistinct(person_id), num_intervals FROM (
         SELECT person_distinct_id.person_id, countDistinct({trunc_func}(toDateTime(timestamp))) as num_intervals
         FROM events
         LEFT JOIN (SELECT person_id, distinct_id FROM person_distinct_id WHERE team_id = %(team_id)s) as person_distinct_id ON person_distinct_id.distinct_id = events.distinct_id
         WHERE team_id = %(team_id)s AND {actions_query} {filters} {parsed_date_from} {parsed_date_to}
         GROUP BY person_distinct_id.person_id
    ) 
    WHERE num_intervals <= %(num_intervals)s
    GROUP BY num_intervals
    ORDER BY num_intervals
"""
