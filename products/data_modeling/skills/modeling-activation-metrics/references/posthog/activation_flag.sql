-- Per-user activation flag + activation rate by signup cohort.
-- Definition (example): activated = ran the key action >= 3 times within 7 days of first ever event.
-- Replace 'key_action' and thresholds with the validated definition (see activation-method.md).
WITH first_seen AS (
    SELECT person_id, min(timestamp) AS signup_at
    FROM events
    WHERE timestamp >= now() - INTERVAL 180 DAY
    GROUP BY person_id
),
early_actions AS (
    SELECT
        e.person_id,
        countIf(e.event = 'key_action'
                AND e.timestamp <= fs.signup_at + INTERVAL 7 DAY) AS key_actions_first_week
    FROM events AS e
    INNER JOIN first_seen AS fs ON e.person_id = fs.person_id
    WHERE e.timestamp >= now() - INTERVAL 180 DAY
    GROUP BY e.person_id
)
SELECT
    toStartOfWeek(fs.signup_at)                                       AS signup_week,
    count()                                                           AS signups,
    countIf(ea.key_actions_first_week >= 3)                          AS activated,
    round(countIf(ea.key_actions_first_week >= 3) / nullif(count(), 0), 4) AS activation_rate
FROM first_seen AS fs
LEFT JOIN early_actions AS ea ON fs.person_id = ea.person_id
GROUP BY signup_week
ORDER BY signup_week
