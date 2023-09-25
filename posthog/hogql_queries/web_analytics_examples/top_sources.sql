WITH

session_cte AS (SELECT events.properties.`$session_id`                                        AS session_id,
                       min(events.timestamp)                                                  AS min_timestamp,
                       max(events.timestamp)                                                  AS max_timestamp,
                       dateDiff('second', min_timestamp, max_timestamp)                       AS duration_s,
                       -- create a tuple so that these are grouped in the same order, see https://github.com/ClickHouse/ClickHouse/discussions/42338
                       groupArray((events.timestamp, events.properties.`$referrer`, events.properties.`$pathname`,
                                   events.properties.utm_source))                             AS tuple_array,
                       arrayFirstIndex(x -> tupleElement(x, 1) == min_timestamp, tuple_array) as index_of_earliest,
                       arrayFirstIndex(x -> tupleElement(x, 1) == max_timestamp, tuple_array) as index_of_latest,
                       tupleElement(arrayElement(
                                            tuple_array,
                                            index_of_earliest
                                        ), 2)                                                 AS earliest_referrer,
                       tupleElement(arrayElement(
                                            tuple_array,
                                            index_of_earliest
                                        ), 3)                                                 AS earliest_pathname,
                       tupleElement(arrayElement(
                                            tuple_array,
                                            index_of_earliest
                                        ), 4)                                                 AS earliest_utm_source,
                       countIf(events.event == '$pageview')                                   AS num_pageviews,
                       countIf(events.event == '$autocapture')                                AS num_autocaptures,
                       -- in v1 we'd also want to count whether there were any conversion events
                       any(events.properties.distinct_id)                                     as distinct_id, -- might want to use person id?
                       -- definition of a GA4 bounce from here https://support.google.com/analytics/answer/12195621?hl=en
                       (num_autocaptures == 0 AND num_pageviews <= 1 AND duration_s < 10)     AS is_bounce
                FROM events
                WHERE session_id IS NOT NULL
                  AND events.timestamp >= now() - INTERVAL 8 DAY
                GROUP BY events.properties.`$session_id`
                HAVING min_timestamp >= now() - INTERVAL 7 DAY)




SELECT
    CASE
        WHEN earliest_utm_source IS NOT NULL THEN earliest_utm_source
        -- todo merge domains and utm_sources, e.g. www.google.com should be merged with google
        ELSE earliest_referrer
    END AS blended_source,
    count(num_pageviews) as total_pageviews,
    count(DISTINCT distinct_id) as unique_visitors,
    avg(is_bounce) AS bounce_rate
FROM
    session_cte
WHERE
    blended_source IS NOT NULL
GROUP BY blended_source

ORDER BY total_pageviews DESC
LIMIT 100


