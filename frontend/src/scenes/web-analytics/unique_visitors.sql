SELECT
    arrayMap(number -> plus(toStartOfHour(assumeNotNull(toDateTime('2024-09-12 00:00:00'))), toIntervalHour(number)), range(0, plus(coalesce(dateDiff('hour', toStartOfHour(assumeNotNull(toDateTime('2024-09-12 00:00:00'))), toStartOfHour(assumeNotNull(toDateTime('2024-09-19 02:59:59'))))), 1))) AS date,
    arrayMap(_match_date -> arraySum(arraySlice(groupArray(count), indexOf(groupArray(day_start) AS _days_for_count, _match_date) AS _index, plus(minus(arrayLastIndex(x -> equals(x, _match_date), _days_for_count), _index), 1))), date) AS total
FROM
    (SELECT
        sum(total) AS count,
        day_start
    FROM
        (SELECT
            count(DISTINCT e.person_id) AS total,
            toStartOfHour(timestamp) AS day_start
        FROM
            events AS e SAMPLE 1
        WHERE
            and(greaterOrEquals(timestamp, assumeNotNull(toDateTime('2024-09-12 00:00:00'))), lessOrEquals(timestamp, assumeNotNull(toDateTime('2024-09-19 02:59:59'))), equals(event, '$pageview'))
        GROUP BY
            day_start)
    GROUP BY
        day_start
    ORDER BY
        day_start ASC)
ORDER BY
    arraySum(total) DESC
LIMIT 50000
UNION ALL
SELECT
    arrayMap(number -> plus(toStartOfHour(assumeNotNull(toDateTime('2024-09-04 00:00:00'))), toIntervalHour(number)), range(0, plus(coalesce(dateDiff('hour', toStartOfHour(assumeNotNull(toDateTime('2024-09-04 00:00:00'))), toStartOfHour(assumeNotNull(toDateTime('2024-09-11 02:59:59'))))), 1))) AS date,
    arrayMap(_match_date -> arraySum(arraySlice(groupArray(count), indexOf(groupArray(day_start) AS _days_for_count, _match_date) AS _index, plus(minus(arrayLastIndex(x -> equals(x, _match_date), _days_for_count), _index), 1))), date) AS total
FROM
    (SELECT
        sum(total) AS count,
        day_start
    FROM
        (SELECT
            count(DISTINCT e.person_id) AS total,
            toStartOfHour(timestamp) AS day_start
        FROM
            events AS e SAMPLE 1
        WHERE
            and(greaterOrEquals(timestamp, assumeNotNull(toDateTime('2024-09-04 00:00:00'))), lessOrEquals(timestamp, assumeNotNull(toDateTime('2024-09-11 02:59:59'))), equals(event, '$pageview'))
        GROUP BY
            day_start)
    GROUP BY
        day_start
    ORDER BY
        day_start ASC)
ORDER BY
    arraySum(total) DESC
LIMIT 50000
