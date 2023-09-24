SELECT
    events.properties.`$session_id` AS session_id,
    -- create a tuple so that these are grouped in the same order, see https://github.com/ClickHouse/ClickHouse/discussions/42338
    groupArray((events.timestamp, events.properties.`$referrer`, events.properties.`$pathname`)) AS tuple_array,
    min(events.timestamp) AS min_timestamp,
    max(events.timestamp) AS max_timestamp,
    dateDiff('second', min_timestamp, max_timestamp) AS duration_s,
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
    countIf(events.event == '$pageview') AS num_pageviews,
    countIf(events.event == '$autocapture') AS num_autocaptures,
    -- definition of a GA4 bounce from here https://support.google.com/analytics/answer/12195621?hl=en
    (num_autocaptures == 0 AND num_pageviews <= 1 AND duration_s < 10) AS is_bounce
FROM
    events
WHERE
    session_id IS NOT NULL
GROUP BY
    events.properties.`$session_id`