-- Stickiness: how many distinct days (out of the last 30) each person did the action, then users per bucket.
-- The high-count buckets are your power users. Replace 'core_action' with the value event.
WITH per_person AS (
    SELECT
        person_id,
        count(DISTINCT toDate(timestamp)) AS active_days
    FROM events
    WHERE event = 'core_action'
      AND timestamp >= now() - INTERVAL 30 DAY
    GROUP BY person_id
)
SELECT
    active_days                                  AS active_days_in_period,
    count()                                      AS users
FROM per_person
GROUP BY active_days
ORDER BY active_days
