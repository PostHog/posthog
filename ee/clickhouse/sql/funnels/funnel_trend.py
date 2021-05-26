FUNNEL_TREND_SQL = """
select addDays(toDate('{start_timestamp}'), number) as date,
       E.distinct_id,
       E.max_step
from numbers(
    dateDiff('day', toDateTime('{start_timestamp}'), toDateTime('{end_timestamp}')) + 1
) as N
left outer join (
    select
        distinct_id,
        windowFunnel(6048000000000000)(toUInt64(toUnixTimestamp64Micro(timestamp)), event = 'step one', event = 'step two', event = 'step three') as max_step,
        arrayJoin(groupArray(toDate(timestamp))) as date
    from events
    group by distinct_id
) as E
on addDays(toDate('{start_timestamp}'), number) = E.date
;
        """
