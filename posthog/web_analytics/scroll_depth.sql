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
ORDER BY total_pageviews DESC