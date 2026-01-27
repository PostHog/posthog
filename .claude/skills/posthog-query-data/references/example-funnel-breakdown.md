# Funnel (two steps, aggregated by unique users, $pageview -> user signed up, broken down by the person's role, sequential, 14-day conversion window)

```sql
SELECT
    sum(step_1) AS step_1,
    sum(step_2) AS step_2,
    arrayMap(x -> if(isNaN(x), NULL, x), [avgArray(step_1_conversion_times)])[1] AS step_1_average_conversion_time,
    arrayMap(x -> if(isNaN(x), NULL, x), [medianArray(step_1_conversion_times)])[1] AS step_1_median_conversion_time,
    groupArray(row_number) AS row_number,
    final_prop
FROM
    (SELECT
        countIf(notEquals(bitAnd(steps_bitfield, 1), 0)) AS step_1,
        countIf(notEquals(bitAnd(steps_bitfield, 2), 0)) AS step_2,
        groupArrayIf(timings[1], greater(timings[1], 0)) AS step_1_conversion_times,
        rowNumberInAllBlocks() AS row_number,
        if(less(row_number, 25), breakdown, ['Other']) AS final_prop
    FROM
        (SELECT
            arraySort(t -> t.1, groupArray(tuple(toFloat(timestamp), uuid, arrayMap(x -> ifNull(x, ''), prop_basic), arrayFilter(x -> notEquals(x, 0), [multiply(1, step_0), multiply(2, step_1)])))) AS events_array,
            argMinIf(prop_basic, timestamp, notEmpty(arrayFilter(x -> notEmpty(x), prop_basic))) AS prop,
            arrayJoin(aggregate_funnel_array(2, 1209600, 'first_touch', 'ordered', [if(empty(prop), [''], prop)], [], arrayFilter((x, x_before, x_after) -> not(and(lessOrEquals(length(x.4), 1), equals(x.4, x_before.4), equals(x.4, x_after.4), equals(x.3, x_before.3), equals(x.3, x_after.3), greater(x.1, x_before.1), less(x.1, x_after.1))), events_array, arrayRotateRight(events_array, 1), arrayRotateLeft(events_array, 1)))) AS af_tuple,
            af_tuple.1 AS step_reached,
            plus(af_tuple.1, 1) AS steps,
            af_tuple.2 AS breakdown,
            af_tuple.3 AS timings,
            af_tuple.5 AS steps_bitfield,
            aggregation_target
        FROM
            (SELECT
                e.timestamp AS timestamp,
                person_id AS aggregation_target,
                e.uuid AS uuid,
                e.$session_id AS $session_id,
                e.$window_id AS $window_id,
                if(equals(event, '$pageview'), 1, 0) AS step_0,
                if(equals(event, 'user signed up'), 1, 0) AS step_1,
                [ifNull(toString(person.properties.role), '')] AS prop_basic,
                prop_basic AS prop
            FROM
                events AS e
            WHERE
                and(and(and(greaterOrEquals(e.timestamp, toDateTime('2026-01-19 00:00:00.000000')), lessOrEquals(e.timestamp, toDateTime('2026-01-26 23:59:59.999999'))), in(event, tuple('$pageview', 'user signed up'))), or(equals(step_0, 1), equals(step_1, 1))))
        GROUP BY
            aggregation_target
        HAVING
            greaterOrEquals(step_reached, 0))
    GROUP BY
        breakdown
    ORDER BY
        step_2 DESC,
        step_1 DESC)
GROUP BY
    final_prop
ORDER BY
    step_2 DESC,
    step_1 DESC
LIMIT 26
```
