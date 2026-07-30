-- Validate a candidate activation definition: does it actually predict retention?
-- Compares week-4 retention of users who met the criteria early vs those who didn't.
-- A good definition shows large, stable lift (retained_activated - retained_not).
WITH first_seen AS (
    SELECT person_id, min(timestamp) AS signup_at
    FROM events
    WHERE timestamp >= now() - INTERVAL 180 DAY
    GROUP BY person_id
),
activated AS (
    SELECT
        e.person_id,
        countIf(e.event = 'key_action'
                AND e.timestamp <= fs.signup_at + INTERVAL 7 DAY) >= 3 AS is_activated
    FROM events AS e
    INNER JOIN first_seen AS fs ON e.person_id = fs.person_id
    GROUP BY e.person_id
),
week4 AS (  -- did the user do anything in their 4th week after signup?
    SELECT
        e.person_id,
        max(e.timestamp >= fs.signup_at + INTERVAL 21 DAY
            AND e.timestamp < fs.signup_at + INTERVAL 28 DAY) AS retained_w4
    FROM events AS e
    INNER JOIN first_seen AS fs ON e.person_id = fs.person_id
    GROUP BY e.person_id
)
SELECT
    a.is_activated                                                   AS activated,
    count()                                                          AS users,
    round(avg(w.retained_w4), 4)                                     AS week4_retention
FROM activated AS a
LEFT JOIN week4 AS w ON a.person_id = w.person_id
GROUP BY activated
ORDER BY activated
