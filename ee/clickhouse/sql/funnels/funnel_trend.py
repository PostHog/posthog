FUNNEL_TREND_SQL = """
select day_start,
    sum(completed) as total_completed_funnels,
    sum(total) as all_funnels_entries,
    cohort
from (
    {funnel_trend_null_sql}
    left outer join (
        select countIf(max_step={step_count}) as completed,
            {interval_method}(when) as start,
            count(1) as total,
            groupArray(person_id) as cohort
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
                     WHERE team_id = %(team_id)s
                ) as pid
                ON pid.distinct_id = events.distinct_id
                WHERE team_id = %(team_id)s
                    {filters}
                    {parsed_date_from}
                    {parsed_date_to}
                GROUP BY pid.person_id
            )
            WHERE max_step > 0
        )
        group by start
    ) as r
    on day_start = r.start
)
group by day_start, cohort
order by day_start;
"""
