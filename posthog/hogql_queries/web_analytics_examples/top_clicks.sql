SELECT
    properties.$el_text as el_text,
    count() as total_clicks,
    COUNT(DISTINCT events.person_id) as unique_visitors
FROM
    events
WHERE
    event == '$autocapture'
AND events.timestamp >= now() - INTERVAL 7 DAY
AND events.properties.$event_type = 'click'
AND el_text IS NOT NULL
GROUP BY
    el_text
ORDER BY total_clicks DESC