# Lifecycle (unique users by pageviews)

```sql
SELECT
    groupArray(start_of_period) AS date,
    groupArray(counts) AS total,
    status
FROM
    (SELECT
        if(equals(status, 'dormant'), negate(sum(counts)), negate(negate(sum(counts)))) AS counts,
        start_of_period,
        status
    FROM
        (SELECT
            periods.start_of_period AS start_of_period,
            0 AS counts,
            status
        FROM
            (SELECT
                minus(toStartOfInterval(assumeNotNull(toDateTime('2026-01-27 23:59:59')), toIntervalDay(1)), toIntervalDay(number)) AS start_of_period
            FROM
                numbers(dateDiff('day', toStartOfInterval(assumeNotNull(toDateTime('2026-01-20 00:00:00')), toIntervalDay(1)), toStartOfInterval(plus(assumeNotNull(toDateTime('2026-01-27 23:59:59')), toIntervalDay(1)), toIntervalDay(1)))) AS numbers) AS periods
            CROSS JOIN (SELECT
                status
            FROM
                (SELECT
                    1)
            ARRAY JOIN ['new', 'returning', 'resurrecting', 'dormant'] AS status) AS sec
        ORDER BY
            status ASC,
            start_of_period ASC
        UNION ALL
        SELECT
            start_of_period,
            count(DISTINCT actor_id) AS counts,
            status
        FROM
            (SELECT
                min(events.person.created_at) AS created_at,
                arraySort(groupUniqArray(toStartOfInterval(events.timestamp, toIntervalDay(1)))) AS all_activity,
                arrayPopBack(arrayPushFront(all_activity, toStartOfInterval(created_at, toIntervalDay(1)))) AS previous_activity,
                arrayPopFront(arrayPushBack(all_activity, toStartOfInterval(toDateTime('1970-01-01 00:00:00'), toIntervalDay(1)))) AS following_activity,
                arrayMap((previous, current, index) -> if(equals(previous, current), 'new', if(and(equals(minus(toTimeZone(current, 'US/Pacific'), toIntervalDay(1)), previous), notEquals(index, 1)), 'returning', 'resurrecting')), previous_activity, all_activity, arrayEnumerate(all_activity)) AS initial_status,
                arrayMap((current, next) -> if(equals(plus(toTimeZone(current, 'US/Pacific'), toIntervalDay(1)), toTimeZone(next, 'US/Pacific')), '', 'dormant'), all_activity, following_activity) AS dormant_status,
                arrayMap(x -> plus(toTimeZone(x, 'US/Pacific'), toIntervalDay(1)), arrayFilter((current, is_dormant) -> equals(is_dormant, 'dormant'), all_activity, dormant_status)) AS dormant_periods,
                arrayMap(x -> 'dormant', dormant_periods) AS dormant_label,
                arrayConcat(arrayZip(all_activity, initial_status), arrayZip(dormant_periods, dormant_label)) AS temp_concat,
                arrayJoin(temp_concat) AS period_status_pairs,
                period_status_pairs.1 AS start_of_period,
                period_status_pairs.2 AS status,
                person_id AS actor_id
            FROM
                events
            WHERE
                and(notEquals(properties.$process_person_profile, 'false'), greaterOrEquals(timestamp, minus(toStartOfInterval(assumeNotNull(toDateTime('2026-01-20 00:00:00')), toIntervalDay(1)), toIntervalDay(1))), less(timestamp, plus(toStartOfInterval(assumeNotNull(toDateTime('2026-01-27 23:59:59')), toIntervalDay(1)), toIntervalDay(1))), equals(event, '$pageview'))
            GROUP BY
                actor_id)
        GROUP BY
            start_of_period,
            status)
    WHERE
        and(lessOrEquals(start_of_period, toStartOfInterval(assumeNotNull(toDateTime('2026-01-27 23:59:59')), toIntervalDay(1))), greaterOrEquals(start_of_period, toStartOfInterval(assumeNotNull(toDateTime('2026-01-20 00:00:00')), toIntervalDay(1))))
    GROUP BY
        start_of_period,
        status
    ORDER BY
        start_of_period ASC)
GROUP BY
    status
LIMIT 50000
```
