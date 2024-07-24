SELECT
    arrayMap(number -> plus(toStartOfDay(assumeNotNull(toDateTime('2024-07-16 00:00:00'))), toIntervalDay(number)), range(0, plus(coalesce(dateDiff('day', toStartOfDay(assumeNotNull(toDateTime('2024-07-16 00:00:00'))), toStartOfDay(assumeNotNull(toDateTime('2024-07-23 23:59:59'))))), 1))) AS date,
    arrayMap(_match_date -> arraySum(arraySlice(groupArray(count), indexOf(groupArray(day_start) AS _days_for_count, _match_date) AS _index, plus(minus(arrayLastIndex(x -> equals(x, _match_date), _days_for_count), _index), 1))), date) AS total
FROM
    (SELECT
        sum(total) AS count,
        day_start
    FROM
        (SELECT
            counts AS total,
            toStartOfDay(timestamp) AS day_start
        FROM
            (SELECT
                d.timestamp,
                count(DISTINCT actor_id) AS counts
            FROM
                (SELECT
                    minus(toStartOfDay(assumeNotNull(toDateTime('2024-07-23 23:59:59'))), toIntervalDay(number)) AS timestamp
                FROM
                    numbers(dateDiff('day', minus(toStartOfDay(assumeNotNull(toDateTime('2024-07-16 00:00:00'))), toIntervalDay(7)), assumeNotNull(toDateTime('2024-07-23 23:59:59')))) AS numbers) AS d
                CROSS JOIN (SELECT
                    timestamp AS timestamp,
                    e.person_id AS actor_id
                FROM
                    events AS e SAMPLE 1
                WHERE
                    and(equals(event, '$pageview'), greaterOrEquals(timestamp, minus(assumeNotNull(toDateTime('2024-07-16 00:00:00')), toIntervalDay(7))), lessOrEquals(timestamp, assumeNotNull(toDateTime('2024-07-23 23:59:59'))))
                GROUP BY
                    timestamp,
                    actor_id) AS e
            WHERE
                and(lessOrEquals(e.timestamp, plus(d.timestamp, toIntervalDay(1))), greater(e.timestamp, minus(d.timestamp, toIntervalDay(6))))
            GROUP BY
                d.timestamp
            ORDER BY
                d.timestamp ASC)
        WHERE
            and(greaterOrEquals(timestamp, toStartOfDay(assumeNotNull(toDateTime('2024-07-16 00:00:00')))), lessOrEquals(timestamp, assumeNotNull(toDateTime('2024-07-23 23:59:59')))))
    GROUP BY
        day_start
    ORDER BY
        day_start ASC)
ORDER BY
    arraySum(total) DESC
LIMIT 50000
