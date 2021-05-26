FUNNEL_TREND_SQL = """
select distinct_id, max_step, when
from (
    select
        distinct_id,
        windowFunnel({window_in_milliseconds})(toUInt64(toUnixTimestamp64Milli(timestamp)), {steps}) as max_step,
        groupArray(timestamp) as when
    from events
    where timestamp >= '{start_timestamp}'
    and timestamp <= '{end_timestamp}'
    group by distinct_id
)
where max_step > 0
"""
