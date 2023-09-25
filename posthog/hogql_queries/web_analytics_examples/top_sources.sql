WITH

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

    if(domain(earliest_referrer) = '', earliest_referrer, domain(earliest_referrer)) AS referrer_domain,
    multiIf(
        earliest_utm_source IS NOT NULL, earliest_utm_source,
        referrer_domain == 'app.posthog.com', 'posthog',
        referrer_domain == 'eu.posthog.com', 'posthog',
        referrer_domain == 'posthog.com', 'posthog',
        referrer_domain == 'www.google.com', 'google',
        referrer_domain == 'www.google.co.uk', 'google',
        referrer_domain == 'www.google.com.hk', 'google',
        referrer_domain == 't.co', 'twitter',
        referrer_domain == 'github.com', 'github',
        referrer_domain == 'bing.com', 'bing',
        referrer_domain == 'yandex.ru', 'yandex',
        referrer_domain == 'quora.com', 'quora',
        referrer_domain
    ) AS blended_source,

    countIf(events.event == '$pageview') AS num_pageviews,
    countIf(events.event == '$autocapture') AS num_autocaptures,
    -- in v1 we'd also want to count whether there were any conversion events

    any(events.person_id) as person_id,
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



SELECT
    blended_source,
    count(num_pageviews) as total_pageviews,
    count(DISTINCT person_id) as unique_visitors,
    avg(is_bounce) AS bounce_rate
FROM
    session_cte
WHERE
    blended_source IS NOT NULL
GROUP BY blended_source

ORDER BY total_pageviews DESC
LIMIT 100


