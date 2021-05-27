FUNNEL_TREND_SQL = """
SELECT distinct_id, max_step, when
FROM (
    SELECT
        distinct_id,
        windowFunnel({within_time})(toUInt64(toUnixTimestamp64Milli(timestamp)),
            {steps}
        ) as max_step,
        groupArray(timestamp) as when
    FROM events
    JOIN (
        SELECT person_id, distinct_id
          FROM ({latest_distinct_id_sql})
         WHERE team_id = %(team_id)s
    ) as pid
    ON pid.distinct_id = events.distinct_id
    WHERE
        team_id = %(team_id)s
        {filters}
        {parsed_date_from}
        {parsed_date_to}
        AND event IN %(events)s
    GROUP BY pid.person_id
    WHERE timestamp >= '{start_timestamp}'
    AND timestamp <= '{end_timestamp}'
    GROUP BY distinct_id
)
WHERE max_step > 0
"""
