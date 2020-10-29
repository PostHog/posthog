FUNNEL_SQL = """
    SELECT 
        person_id as id,
        windowFunnel(6048000000000000)(toUInt64(toUnixTimestamp64Micro(timestamp)),
            {steps}
        )
    FROM (
        SELECT
            events.*, pid.person_id
        FROM
            events
        JOIN (SELECT person_id, distinct_id FROM person_distinct_id WHERE team_id = %(team_id)s) as pid
        ON pid.distinct_id = events.distinct_id
        WHERE team_id = %(team_id)s {filters} {parsed_date_from} {parsed_date_to}
    )
    GROUP BY person_id
"""
