FUNNEL_TREND_SQL = """
select interval_date,
    sum(completed) as total_completed_funnels,
    sum(total) as all_funnels_entries
from (
    {null_sql}
    union all
    select countIf(max_step={step_count}) as completed,
        {interval_method}(when) as start,
        count(1) as total
    from (
        SELECT person_id, max_step, when
        FROM (
            SELECT
                pid.person_id,
                windowFunnel({within_time})(toUInt64(toUnixTimestamp64Milli(timestamp)),
                    {steps}
                ) as max_step,
                max(timestamp) as when
            FROM events
            JOIN (
                SELECT person_id, distinct_id
                  FROM ({latest_distinct_id_sql})
                 WHERE team_id = {team_id}
            ) as pid
            ON pid.distinct_id = events.distinct_id
            WHERE team_id = {team_id}
                {filters}
                {parsed_date_from}
                {parsed_date_to}
            GROUP BY pid.person_id
        )
        WHERE max_step > 0
    )
    group by start
)
group by interval_date
order by interval_date;
"""
