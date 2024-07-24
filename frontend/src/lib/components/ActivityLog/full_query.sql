SELECT
    arrayMap(number -> plus(toStartOfDay(assumeNotNull(toDateTime('2024-07-16 00:00:00'))), toIntervalDay(number)), range(0, plus(coalesce(dateDiff('day', toStartOfDay(assumeNotNull(toDateTime('2024-07-16 00:00:00'))), toStartOfDay(assumeNotNull(toDateTime('2024-07-23 23:59:59'))))), 1))) AS date,
    arrayMap(_match_date -> arraySum(arraySlice(groupArray(count), indexOf(groupArray(day_start) AS _days_for_count, _match_date) AS _index, plus(minus(arrayLastIndex(x -> equals(x, _match_date), _days_for_count), _index), 1))), date) AS total
FROM
    (SELECT
        sum(total) AS count,
        day_start
    FROM (SELECT
            count() AS total,
            day_start,
            breakdown_value
        FROM (
            SELECT
                min(timestamp) as day_start,
                argMin(breakdown_value, timestamp) AS breakdown_value,
            FROM
                (
                    SELECT
                        person_id,
                        toStartOfDay(timestamp) AS timestamp,
                        ifNull(nullIf(toString(person.properties.email), ''), '$$_posthog_breakdown_null_$$') AS breakdown_value
                    FROM
                        events AS e SAMPLE 1
                    WHERE
                        and(lessOrEquals(timestamp, assumeNotNull(toDateTime('2024-07-23 23:59:59'))), equals(properties.$browser, 'Safari'))
                )
            WHERE
                greaterOrEquals(timestamp, toStartOfDay(assumeNotNull(toDateTime('2024-07-16 00:00:00'))))
            GROUP BY
                person_id
        )
        GROUP BY
            day_start,
            breakdown_value)
    GROUP BY
        day_start
    ORDER BY
        day_start ASC)
ORDER BY
    arraySum(total) DESC
LIMIT 50000
