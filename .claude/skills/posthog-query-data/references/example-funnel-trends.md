# Conversion trends (funnel, two steps, $pageview -> user signed up, aggregated by unique groups, 1-day conversion window)

```sql
SELECT
    fill.entrance_period_start AS entrance_period_start,
    countIf(notEquals(success_bool, 0)) AS reached_from_step_count,
    countIf(equals(success_bool, 1)) AS reached_to_step_count,
    if(greater(reached_from_step_count, 0), round(multiply(divide(reached_to_step_count, reached_from_step_count), 100), 2), 0) AS conversion_rate,
    breakdown AS prop
FROM
    (SELECT
        arraySort(t -> t.1, groupArray(tuple(toFloat(timestamp), _toUInt64(toDateTime(toStartOfDay(timestamp))), uuid, '', arrayFilter(x -> notEquals(x, 0), [multiply(1, step_0), multiply(2, step_1)])))) AS events_array,
        [''] AS prop,
        arrayJoin(aggregate_funnel_trends(1, 2, 2, 86400, 'last_touch', 'strict', prop, events_array)) AS af_tuple,
        toTimeZone(toDateTime(_toUInt64(af_tuple.1)), 'US/Pacific') AS entrance_period_start,
        af_tuple.2 AS success_bool,
        af_tuple.3 AS breakdown,
        aggregation_target AS aggregation_target
    FROM
        (SELECT
            e.timestamp AS timestamp,
            $group_0 AS aggregation_target,
            e.uuid AS uuid,
            if(equals(event, '$pageview'), 1, 0) AS step_0,
            if(equals(event, 'user signed up'), 1, 0) AS step_1
        FROM
            events AS e
        WHERE
            and(greaterOrEquals(e.timestamp, toDateTime('2026-01-19 00:00:00.000000')), lessOrEquals(e.timestamp, toDateTime('2026-01-26 23:59:59.999999'))))
    GROUP BY
        aggregation_target) AS data
    RIGHT OUTER JOIN (SELECT
        plus(toStartOfDay(assumeNotNull(toDateTime(('2026-01-19 00:00:00')))), toIntervalDay(number)) AS entrance_period_start
    FROM
        numbers(plus(dateDiff('day', toStartOfDay(assumeNotNull(toDateTime(('2026-01-19 00:00:00')))), toStartOfDay(assumeNotNull(toDateTime(('2026-01-26 23:59:59'))))), 1)) AS period_offsets) AS fill ON equals(data.entrance_period_start, fill.entrance_period_start)
GROUP BY
    entrance_period_start,
    data.breakdown
ORDER BY
    entrance_period_start ASC
LIMIT 1000
```
