-- Overall conversion rate broken down by a first-touch property (here: signup channel).
-- Attribution = first-touch: each person's breakdown value is taken from their first step-1 event.
WITH first_touch AS (
    SELECT
        person_id,
        argMin(properties.$initial_utm_source, timestamp) AS channel  -- value at first event
    FROM events
    WHERE event = 'signed_up'
      AND timestamp >= now() - INTERVAL 90 DAY
    GROUP BY person_id
),
per_person AS (
    SELECT
        person_id,
        windowFunnel(1209600)(
            toDateTime(timestamp),  -- toDateTime: `timestamp` is DateTime64, which windowFunnel rejects
            event = 'signed_up',
            event = 'purchased'
        ) AS steps_completed
    FROM events
    WHERE event IN ('signed_up', 'purchased')
      AND timestamp >= now() - INTERVAL 90 DAY
    GROUP BY person_id
)
SELECT
    coalesce(f.channel, '(none)')                                            AS channel,
    count()                                                                  AS entered,
    countIf(p.steps_completed >= 2)                                          AS converted,
    round(countIf(p.steps_completed >= 2) / nullif(count(), 0), 4)           AS conversion_rate
FROM per_person AS p
LEFT JOIN first_touch AS f ON p.person_id = f.person_id
GROUP BY channel
ORDER BY entered DESC
