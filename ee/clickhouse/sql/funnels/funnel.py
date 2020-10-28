FUNNEL_SQL = """
    SELECT 
        person_distinct_id.person_id as id,
        windowFunnel(6048000000000000)(toDateTime(timestamp),
            {steps}
        )
    FROM events 
    JOIN (SELECT person_id, distinct_id FROM person_distinct_id WHERE team_id = %(team_id)s) as person_distinct_id ON person_distinct_id.distinct_id = events.distinct_id
    {person_prop_join}
    WHERE team_id = %(team_id)s {filters} {parsed_date_from} {parsed_date_to}
    GROUP BY person_distinct_id.person_id, team_id
"""
