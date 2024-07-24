SELECT
    count() AS total,
    toStartOfDay(min_timestamp) AS day_start,
    breakdown_value AS breakdown_value
FROM
    (SELECT
        min(timestamp) AS min_timestamp,
        argMin(breakdown_value, timestamp) AS breakdown_value
    FROM
        (SELECT
            person_id,
            timestamp,
            ifNull(nullIf(toString(properties.$browser), ''), '$$_posthog_breakdown_null_$$') AS breakdown_value
        FROM
            events AS e SAMPLE 1
        WHERE
            and(equals(event, '$pageview'), lessOrEquals(timestamp, assumeNotNull(toDateTime('2025-01-20 23:59:59'))))
       )
    GROUP BY
        person_id
        )
WHERE
    greaterOrEquals(min_timestamp, toStartOfDay(assumeNotNull(toDateTime('2020-01-09 00:00:00'))))
GROUP BY
    day_start,
    breakdown_value
LIMIT 50000
