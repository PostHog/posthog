-- Per-user activation flag + activation rate by signup cohort.
-- Definition (example): activated = ran the key action >= 3 times within 7 days of first-ever event.
-- Replace 'key_action' and thresholds with the validated definition (see activation-method.md).
--
-- signup_at must be the user's FIRST-EVER event, computed over full history. Filtering events to a
-- reporting window BEFORE the min() would hand a long-lived, recently-active user a brand-new
-- "signup" date and wrongly count them as freshly activated. So compute first-ever first, then
-- restrict the report to recent cohorts. (Materialize first_seen if the full-history scan is heavy.)
WITH first_seen AS (
    SELECT person_id, min(timestamp) AS signup_at
    FROM events
    GROUP BY person_id
),
cohort AS (
    -- the signup cohorts to report on; this filter does not affect signup_at itself
    SELECT person_id, signup_at
    FROM first_seen
    WHERE signup_at >= now() - INTERVAL 180 DAY
),
early_actions AS (
    SELECT
        c.person_id,
        countIf(e.event = 'key_action'
                AND e.timestamp <= c.signup_at + INTERVAL 7 DAY) AS key_actions_first_week
    FROM events AS e
    INNER JOIN cohort AS c ON e.person_id = c.person_id
    GROUP BY c.person_id
)
SELECT
    toStartOfWeek(c.signup_at)                                       AS signup_week,
    count()                                                          AS signups,
    countIf(ea.key_actions_first_week >= 3)                          AS activated,
    round(countIf(ea.key_actions_first_week >= 3) / nullif(count(), 0), 4) AS activation_rate
FROM cohort AS c
LEFT JOIN early_actions AS ea ON c.person_id = ea.person_id
GROUP BY signup_week
ORDER BY signup_week
