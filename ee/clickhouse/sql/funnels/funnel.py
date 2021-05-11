FUNNEL_SQL = """
SELECT max_step {top_level_groupby}, count(1), groupArray(100)(id) FROM (
    SELECT
        pid.uid as id,
        {extra_select}
        windowFunnel({within_time})(toUInt64(toUnixTimestamp64Micro(timestamp)),
            {steps}
        ) as max_step
    FROM 
        events
    {event_join}
    WHERE
        team_id = %(team_id)s {filters} {parsed_date_from} {parsed_date_to}
        AND event IN %(events)s
    GROUP BY pid.uid {extra_groupby}
)
WHERE max_step > 0
GROUP BY max_step {top_level_groupby}
ORDER BY max_step {top_level_groupby} ASC
;
"""
