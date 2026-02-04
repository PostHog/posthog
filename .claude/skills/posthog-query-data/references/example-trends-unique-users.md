# Trends (unique users, for specific 90 days)

```sql
SELECT
    sum(total) AS count,
    day_start
FROM
    (SELECT
        count(DISTINCT e.person_id) AS total,
        toStartOfDay(timestamp) AS day_start
    FROM
        events AS e
    WHERE
        and(greaterOrEquals(timestamp, toStartOfInterval(assumeNotNull(toDateTime('2025-12-27 00:00:00')), toIntervalDay(1))), lessOrEquals(timestamp, assumeNotNull(toDateTime('2026-01-26 23:59:59'))), equals(event, 'chat with ai'))
    GROUP BY
        day_start)
GROUP BY
    day_start
ORDER BY
    day_start ASC
```
