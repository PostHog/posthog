-- Reference feature SQL (fixture bundle, slice 1).
--
-- Same {anchors} contract the agent must follow: the framework substitutes
-- {anchors} with a per-user (person_id, cutoff_ts) table — per-user T0 at
-- training, now() at inference — and substitutes {lookback_days} with the
-- rolling-window size. Events are read strictly before each user's cutoff_ts
-- so features never peek into the label window.
SELECT
    a.person_id AS distinct_id,
    count(e.uuid) AS events_total,
    uniqIf(e.event, e.event NOT LIKE '$%') AS unique_user_events,
    countIf(e.event = '$pageview') AS pageviews,
    countIf(e.event = 'uploaded_file') AS uploads,
    countIf(e.event = 'downloaded_file') AS downloads,
    dateDiff('day', max(e.timestamp), fromUnixTimestamp(a.cutoff_ts)) AS days_since_last_event
FROM {anchors} a
LEFT JOIN events e
    ON e.person_id = a.person_id
    AND e.timestamp <  fromUnixTimestamp(a.cutoff_ts)
    AND e.timestamp >= fromUnixTimestamp(a.cutoff_ts) - toIntervalDay({lookback_days})
GROUP BY a.person_id
