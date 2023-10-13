# The intention is for these CTEs to become materialized views for performance reasons, but
# while these queries are under development they are left as CTEs so that they can be iterated
# on without needing database migrations

SESSION_CTE = """
SELECT
    events.properties.`$session_id` AS session_id,
    min(events.timestamp) AS min_timestamp,
    max(events.timestamp) AS max_timestamp,
    dateDiff('second', min_timestamp, max_timestamp) AS duration_s,

    any(events.properties.$initial_referring_domain) AS $initial_referring_domain,
    any(events.properties.$set_once.$initial_pathname) AS $initial_pathname,
    any(events.properties.$set_once.$initial_utm_source) AS $initial_utm_source,

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
    AND ({session_where})
GROUP BY
    events.properties.`$session_id`
HAVING
    ({session_having})
    """

SOURCE_CTE = """
SELECT
    events.properties.$set_once.$initial_utm_source AS $initial_utm_source,
    count() as total_pageviews,
    uniq(events.person_id) as unique_visitors
FROM
    events
WHERE
    (event = '$pageview')
    AND ({source_where})
    GROUP BY $initial_utm_source
"""

PATHNAME_CTE = """
SELECT
    events.properties.`$pathname` AS $pathname,
    count() as total_pageviews,
    uniq(events.person_id) as unique_visitors
FROM
    events
WHERE
    (event = '$pageview')
    AND ({pathname_where})
    GROUP BY $pathname
"""

PATHNAME_SCROLL_CTE = """
SELECT
    events.properties.`$prev_pageview_pathname` AS $pathname,
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
    AND ({pathname_scroll_where})
GROUP BY $pathname
"""
