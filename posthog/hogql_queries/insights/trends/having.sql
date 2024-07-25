SELECT
    toStartOfDay(min(timestamp)) as day_start,
    argMin(ifNull(nullIf(toString(person.properties.email), ''), '$$_posthog_breakdown_null_$$'), timestamp) AS breakdown_value
FROM
    events AS e SAMPLE 1
WHERE
    lessOrEquals(timestamp, assumeNotNull(toDateTime('2024-07-23 23:59:59'))) and event = '$pageview'
GROUP BY
    person_id
HAVING
    equals(properties.$browser, 'Safari')
