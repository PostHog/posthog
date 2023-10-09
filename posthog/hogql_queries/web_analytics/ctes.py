# The intention is for these CTEs to become materialized views for performance reasons, but
# while these queries are under development they are left as CTEs so that they can be iterated
# on without needing database migrations

SESSION_CTE = """
SELECT
    events.properties.`$session_id` AS session_id,
    min(events.timestamp) AS min_timestamp,
    max(events.timestamp) AS max_timestamp,
    dateDiff('second', min_timestamp, max_timestamp) AS duration_s,

    argMin(events.properties.`$referrer`, events.timestamp) AS earliest_referrer,
    argMin(events.properties.`$pathname`, events.timestamp) AS earliest_pathname,
    argMax(events.properties.`$pathname`, events.timestamp ) AS latest_pathname,
    argMax(events.properties.utm_source, events.timestamp) AS earliest_utm_source,

    if(domain(earliest_referrer) = '', earliest_referrer, domain(earliest_referrer)) AS referrer_domain,
    multiIf(
        earliest_utm_source IS NOT NULL, earliest_utm_source,
        -- This will need to be an approach that scales better
        referrer_domain == 'app.posthog.com', 'posthog',
        referrer_domain == 'eu.posthog.com', 'posthog',
        referrer_domain == 'posthog.com', 'posthog',
        referrer_domain == 'www.google.com', 'google',
        referrer_domain == 'www.google.co.uk', 'google',
        referrer_domain == 'www.google.com.hk', 'google',
        referrer_domain == 'www.google.de', 'google',
        referrer_domain == 't.co', 'twitter',
        referrer_domain == 'github.com', 'github',
        referrer_domain == 'duckduckgo.com', 'duckduckgo',
        referrer_domain == 'www.bing.com', 'bing',
        referrer_domain == 'bing.com', 'bing',
        referrer_domain == 'yandex.ru', 'yandex',
        referrer_domain == 'quora.com', 'quora',
        referrer_domain == 'www.quora.com', 'quora',
        referrer_domain == 'linkedin.com', 'linkedin',
        referrer_domain == 'www.linkedin.com', 'linkedin',
        startsWith(referrer_domain, 'http://localhost:'), 'localhost',
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
    """

PATHNAME_CTE = """
SELECT
    events.properties.`$pathname` AS pathname,
    count() as total_pageviews,
    uniq(events.person_id) as unique_visitors -- might want to use person id? have seen a small number of pages where unique > total
FROM
    events
WHERE
    (event = '$pageview')
    AND events.timestamp >= now() - INTERVAL 7 DAY
GROUP BY pathname
"""

PATHNAME_SCROLL_CTE = """
SELECT
    events.properties.`$prev_pageview_pathname` AS pathname,
    avg(CASE
        WHEN toFloat(JSONExtractRaw(events.properties, '$prev_pageview_max_content_percentage')) IS NULL THEN NULL
        WHEN toFloat(JSONExtractRaw(events.properties, '$prev_pageview_max_content_percentage')) > 0.8 THEN 100
        ELSE 0
    END) AS scroll_gt80_percentage,
    avg(toFloat(JSONExtractRaw(events.properties, '$prev_pageview_max_scroll_percentage'))) as average_scroll_percentage
FROM
    events
WHERE
    (event = '$pageview' OR event = '$pageleave') AND events.properties.`$prev_pageview_pathname` IS NOT NULL
    AND events.timestamp >= now() - INTERVAL 7 DAY
GROUP BY pathname
"""
