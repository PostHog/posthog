WITH

scroll_depth_cte AS (
SELECT
    events.properties.`$prev_pageview_pathname` AS pathname,
    countIf(events.event == '$pageview') as total_pageviews,
    COUNT(DISTINCT events.properties.distinct_id) as unique_visitors, -- might want to use person id? have seen a small number of pages where unique > total
    avg(CASE
        WHEN events.properties.`$prev_pageview_max_content_percentage` IS NULL THEN NULL
        WHEN events.properties.`$prev_pageview_max_content_percentage` > 0.8 THEN 100
        ELSE 0
    END) AS scroll_gt80_percentage,
    avg(events.properties.$prev_pageview_max_scroll_percentage) * 100 as average_scroll_percentage
FROM
    events
WHERE
    (event = '$pageview' OR event = '$pageleave') AND events.properties.`$prev_pageview_pathname` IS NOT NULL
    AND events.timestamp >= now() - INTERVAL 7 DAY
GROUP BY pathname
)

,

session_cte AS (
 SELECT
    events.properties.`$session_id` AS session_id,
    min(events.timestamp) AS min_timestamp,
    max(events.timestamp) AS max_timestamp,
    dateDiff('second', min_timestamp, max_timestamp) AS duration_s,
    -- create a tuple so that these are grouped in the same order, see https://github.com/ClickHouse/ClickHouse/discussions/42338
    groupArray((events.timestamp, events.properties.`$referrer`, events.properties.`$pathname`, events.properties.utm_source)) AS tuple_array,
    arrayFirstIndex(x -> tupleElement(x, 1) == min_timestamp, tuple_array) as index_of_earliest,
    arrayFirstIndex(x -> tupleElement(x, 1) == max_timestamp, tuple_array) as index_of_latest,
    tupleElement(arrayElement(
        tuple_array,
        index_of_earliest
    ), 2) AS earliest_referrer,
    tupleElement(arrayElement(
        tuple_array,
        index_of_earliest
    ), 3) AS earliest_pathname,
    tupleElement(arrayElement(
        tuple_array,
        index_of_earliest
    ), 4) AS earliest_utm_source,
    countIf(events.event == '$pageview') AS num_pageviews,
    countIf(events.event == '$autocapture') AS num_autocaptures,
    -- in v1 we'd also want to count whether there were any conversion events
    any(events.properties.distinct_id) as distinct_id, -- might want to use person id?
    -- definition of a GA4 bounce from here https://support.google.com/analytics/answer/12195621?hl=en
    (num_autocaptures == 0 AND num_pageviews <= 1 AND duration_s < 10) AS is_bounce
FROM
    events
WHERE
    session_id IS NOT NULL
AND
    events.timestamp >= now() - INTERVAL 8 DAY
GROUP BY
    events.properties.`$session_id`
HAVING
    min_timestamp >= now() - INTERVAL 7 DAY
)

,

bounce_rate_cte AS (
SELECT session_cte.earliest_pathname,
       avg(session_cte.is_bounce) as bounce_rate
FROM session_cte
GROUP BY earliest_pathname
)



SELECT scroll_depth_cte.pathname as pathname,
scroll_depth_cte.total_pageviews as total_pageviews,
scroll_depth_cte.unique_visitors as unique_visitors,
scroll_depth_cte.scroll_gt80_percentage as scroll_gt80_percentage,
scroll_depth_cte.average_scroll_percentage as average_scroll_percentage,
bounce_rate_cte.bounce_rate as bounce_rate
FROM
    scroll_depth_cte LEFT OUTER JOIN bounce_rate_cte
ON scroll_depth_cte.pathname = bounce_rate_cte.earliest_pathname
ORDER BY total_pageviews DESC



