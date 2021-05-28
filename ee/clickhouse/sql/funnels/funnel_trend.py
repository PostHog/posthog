FUNNEL_TREND_SQL = """
SELECT distinct_id, max_step, when
FROM (
    SELECT
        pid.person_id,
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
)
WHERE max_step > 0
"""

FUNNEL_TREND_SQL_2 = """
select day_start, sum(completed) as total_completed_funnels, sum(total) as all_funnels_entries
from (
    SELECT toUInt16(0) AS completed,
        toStartOfDay(toDateTime('2021-05-07 00:00:00') - number * 86400) as day_start,
        toUInt16(0) AS total
    FROM numbers(7)
    union all
    select countIf(max_step=3) as completed,
        toStartOfDay(when) as start,
        count(1) as total
    from (
        SELECT distinct_id, max_step, when
        FROM (
          SELECT
          distinct_id,
          windowFunnel(604800000)(toUInt64(toUnixTimestamp64Milli(timestamp)),
          event = 'step one', event = 'step two', event = 'step three'
          ) as max_step,
          max(timestamp) as when
          FROM events
          WHERE events.team_id = 1
          and events.timestamp >= '2021-05-01 00:00:00'
          and events.timestamp <= '2021-05-07 00:00:00'
          AND event IN ('step one', 'step two', 'step three')
          GROUP BY distinct_id
          )
        WHERE max_step > 0
    )
    group by start
)
group by day_start
order by day_start;
"""
