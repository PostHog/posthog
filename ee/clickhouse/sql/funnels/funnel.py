FUNNEL_SQL = """
SELECT max_step, count(1), groupArray(100)(id) FROM (
    SELECT
        person_id as id,
        windowFunnel({within_time})(toUInt64(toUnixTimestamp64Micro(timestamp)),
            {steps}
        ) as max_step
    FROM ({event_query})
    GROUP BY person_id
)
WHERE max_step > 0
GROUP BY max_step
ORDER BY max_step ASC
;
"""
