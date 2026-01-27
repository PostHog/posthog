# Trends (total event count, specific week)

```sql
SELECT
    sum(total) AS count,
    day_start,
    [breakdown_value_1, if(empty(arrayFilter(x -> and(lessOrEquals(x[1], breakdown_value_2), less(breakdown_value_2, x[2])), buckets[1])[1]), '$$_posthog_breakdown_null_$$', ifNull(nullIf(toString(arrayFilter(x -> and(lessOrEquals(x[1], breakdown_value_2), less(breakdown_value_2, x[2])), buckets[1])[1]), ''), '$$_posthog_breakdown_null_$$'))] AS breakdown_value
FROM
    (SELECT
        count() AS total,
        toStartOfDay(timestamp) AS day_start,
        ifNull(nullIf(toString(properties.$browser), ''), '$$_posthog_breakdown_null_$$') AS breakdown_value_1,
        properties.$browser_version AS breakdown_value_2,
        (SELECT
                [max(breakdown_value_2)]
            FROM
                (SELECT
                    count() AS total,
                    toStartOfDay(timestamp) AS day_start,
                    ifNull(nullIf(toString(properties.$browser), ''), '$$_posthog_breakdown_null_$$') AS breakdown_value_1,
                    properties.$browser_version AS breakdown_value_2
                FROM
                    events AS e
                WHERE
                    and(greaterOrEquals(timestamp, toStartOfInterval(assumeNotNull(toDateTime('2026-01-19 00:00:00')), toIntervalDay(1))), lessOrEquals(timestamp, assumeNotNull(toDateTime('2026-01-26 23:59:59'))))
                GROUP BY
                    day_start,
                    breakdown_value_1,
                    breakdown_value_2) AS min_max) AS max_nums,
        (SELECT
                [min(breakdown_value_2)]
            FROM
                (SELECT
                    count() AS total,
                    toStartOfDay(timestamp) AS day_start,
                    ifNull(nullIf(toString(properties.$browser), ''), '$$_posthog_breakdown_null_$$') AS breakdown_value_1,
                    properties.$browser_version AS breakdown_value_2
                FROM
                    events AS e
                WHERE
                    and(greaterOrEquals(timestamp, toStartOfInterval(assumeNotNull(toDateTime('2026-01-19 00:00:00')), toIntervalDay(1))), lessOrEquals(timestamp, assumeNotNull(toDateTime('2026-01-26 23:59:59'))))
                GROUP BY
                    day_start,
                    breakdown_value_1,
                    breakdown_value_2) AS min_max) AS min_nums,
        arrayMap((max_num, min_num) -> minus(max_num, min_num), arrayZip(max_nums, min_nums)) AS diff,
        [10] AS bins,
        arrayMap(i -> arrayMap(x -> [plus(multiply(divide(diff[i], bins[i]), x), min_nums[i]), plus(plus(multiply(divide(diff[i], bins[i]), plus(x, 1)), min_nums[i]), if(equals(plus(x, 1), bins[i]), 0.01, 0))], range(bins[i])), range(1, 2)) AS buckets
    FROM
        events AS e
    WHERE
        and(greaterOrEquals(timestamp, toStartOfInterval(assumeNotNull(toDateTime('2026-01-19 00:00:00')), toIntervalDay(1))), lessOrEquals(timestamp, assumeNotNull(toDateTime('2026-01-26 23:59:59'))), equals(event, '$pageview'))
    GROUP BY
        day_start,
        breakdown_value_1,
        breakdown_value_2)
GROUP BY
    day_start,
    breakdown_value
ORDER BY
    day_start ASC,
    breakdown_value ASC
```
