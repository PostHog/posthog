
WITH scroll_depth_cte AS (
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
GROUP BY pathname
),

bounce_rate_cte AS (
SELECT
    events.properties.$pathname as pathname,
    countIf(events.event == '$pageview') as total_pageviews,
    (COUNT(DISTINCT CASE
        WHEN (raw_session_replay_events.click_count = 0 AND raw_session_replay_events.active_milliseconds < 60000)
        THEN raw_session_replay_events.session_id
        ELSE NULL
    END) * 100.0) / COUNT(DISTINCT raw_session_replay_events.session_id) AS bounce_rate
FROM
    events
INNER JOIN
    raw_session_replay_events ON events.properties.$session_id = raw_session_replay_events.session_id
WHERE
    created_at >= now() - INTERVAL 7 DAY
GROUP BY
    pathname
ORDER BY total_pageviews DESC

)

SELECT scroll_depth_cte.pathname as pathname,
scroll_depth_cte.total_pageviews as total_pageviews,
bounce_rate_cte.total_pageviews as total_pageviews_2,
scroll_depth_cte.unique_visitors as unique_visitors,
scroll_depth_cte.scroll_gt80_percentage as scroll_gt80_percentage,
scroll_depth_cte.average_scroll_percentage as average_scroll_percentage,
bounce_rate_cte.bounce_rate as bounce_rate
FROM
    scroll_depth_cte LEFT OUTER JOIN bounce_rate_cte
ON scroll_depth_cte.pathname = bounce_rate_cte.pathname
ORDER BY total_pageviews DESC



