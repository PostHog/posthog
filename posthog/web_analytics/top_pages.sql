SELECT
    events.properties.$pathname as pathname,
    countIf(event == '$pageview') as total_pageviews,
    COUNT(DISTINCT events.properties.distinct_id) as unique_visitors, -- might want to use person id? have seen a small number of pages where unique > total
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
    AND {filters}
GROUP BY
    pathname
ORDER BY total_pageviews DESC
LIMIT 1000