-- Validate a candidate activation definition: does it actually predict retention?
-- Compares week-4 retention of users who met the criteria early vs those who didn't.
-- A good definition shows large, stable lift (retained_activated - retained_not).
--
-- Two correctness guards:
--  1. signup_at is the FIRST-EVER event (full history), not the first event in a lookback window —
--     else a long-lived, recently-active user gets a false-new signup date.
--  2. Only cohorts old enough for a full week-4 window count. Recent signups that haven't reached
--     day 28 would score retained_w4 = 0 and drag the lift down (right-censoring), so exclude them.
WITH first_seen AS (
    SELECT person_id, min(timestamp) AS signup_at
    FROM events
    GROUP BY person_id
),
cohort AS (
    -- eligible cohorts: recent enough to report on, but old enough to have a complete week 4
    SELECT person_id, signup_at
    FROM first_seen
    WHERE signup_at >= now() - INTERVAL 180 DAY
      AND signup_at <= now() - INTERVAL 28 DAY
),
activated AS (
    SELECT
        c.person_id,
        countIf(e.event = 'key_action'
                AND e.timestamp <= c.signup_at + INTERVAL 7 DAY) >= 3 AS is_activated
    FROM events AS e
    INNER JOIN cohort AS c ON e.person_id = c.person_id
    GROUP BY c.person_id
),
week4 AS (  -- did the user do anything in their 4th week after signup?
    SELECT
        c.person_id,
        max(e.timestamp >= c.signup_at + INTERVAL 21 DAY
            AND e.timestamp < c.signup_at + INTERVAL 28 DAY) AS retained_w4
    FROM events AS e
    INNER JOIN cohort AS c ON e.person_id = c.person_id
    GROUP BY c.person_id
)
SELECT
    a.is_activated                                                   AS activated,
    count()                                                          AS users,
    round(avg(w.retained_w4), 4)                                     AS week4_retention
FROM activated AS a
LEFT JOIN week4 AS w ON a.person_id = w.person_id
GROUP BY activated
ORDER BY activated
