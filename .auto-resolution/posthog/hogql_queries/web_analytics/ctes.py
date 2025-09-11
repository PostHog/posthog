# The intention is for these CTEs to become materialized views for performance reasons, but
# while these queries are under development they are left as CTEs so that they can be iterated
# on without needing database migrations

PATHNAME_SCROLL_CTE = """
SELECT
    events.properties.`$prev_pageview_pathname` AS pathname,
    avg(CASE
        WHEN toFloat(JSONExtractRaw(events.properties, '$prev_pageview_max_content_percentage')) IS NULL THEN NULL
        WHEN toFloat(JSONExtractRaw(events.properties, '$prev_pageview_max_content_percentage')) > 0.8 THEN 1
        ELSE 0
    END) AS scroll_gt80_percentage,
    avg(toFloat(JSONExtractRaw(events.properties, '$prev_pageview_max_scroll_percentage'))) as average_scroll_percentage
FROM
    events
SAMPLE {sample_rate}
WHERE
    (event = '$pageview' OR event = '$pageleave') AND events.properties.`$prev_pageview_pathname` IS NOT NULL
    AND ({pathname_scroll_where})
GROUP BY pathname
"""

COUNTS_CTE = """
SELECT
    {breakdown_by} AS breakdown_value,
    count() as total_pageviews,
    uniq(events.person_id) as unique_visitors
FROM
    events
SAMPLE {sample_rate}
WHERE
    (event = '$pageview')
    AND ({counts_where})
    GROUP BY breakdown_value
"""

SESSION_CTE = """
    SELECT
        events.properties.`$session_id` AS session_id,
        min(events.timestamp) AS min_timestamp,
        max(events.timestamp) AS max_timestamp,
        dateDiff('second', min_timestamp, max_timestamp) AS duration_s,
        countIf(events.event == '$pageview') AS num_pageviews,
        countIf(events.event == '$autocapture') AS num_autocaptures,
        any(events.properties.$initial_pathname) AS session_initial_pathname, -- TODO use session initial rather than user initial
        {breakdown_by} AS breakdown_value,

        -- definition of a GA4 bounce from here https://support.google.com/analytics/answer/12195621?hl=en
        (num_autocaptures == 0 AND num_pageviews <= 1 AND duration_s < 10) AS is_bounce
    FROM
        events
    SAMPLE {sample_rate}
    WHERE
        session_id IS NOT NULL
        AND (events.event == '$pageview' OR events.event == '$autocapture' OR events.event == '$pageleave')
        AND ({session_where})
    GROUP BY
        events.properties.`$session_id`
    HAVING
        ({session_having})
    """

# This pulls in SESSION_CTE using f-strings rather than HogQL placeholders, which is safe
# but means that when you use parse_select on it, you'll need to make sure you include the
# placeholders that SESSION_CTE needs.
BOUNCE_RATE_CTE = f"""
SELECT
    breakdown_value,
    avg(session.is_bounce) as bounce_rate
FROM (
  {SESSION_CTE}
) AS session
GROUP BY
    breakdown_value
    """
