FUNNEL_SQL = """
SELECT max_step, count(1), groupArray(100)(id) FROM (
    SELECT
        pid.person_id as id,
        windowFunnel(6048000000000000)(toUInt64(toUnixTimestamp64Micro(timestamp)),
            {steps}
        ) as max_step
    FROM 
        events
    JOIN (
        SELECT person_id, distinct_id FROM person_distinct_id WHERE team_id = %(team_id)s
    ) as pid
    ON pid.distinct_id = events.distinct_id
    WHERE
        team_id = %(team_id)s {filters} {parsed_date_from} {parsed_date_to}
        AND event IN %(events)s
    GROUP BY pid.person_id
)
WHERE max_step > 0
GROUP BY max_step
ORDER BY max_step ASC
;
"""
