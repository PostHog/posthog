-- Weekly retention matrix: % active in each subsequent week, by acquisition cohort.
-- Recurring definition (active IN week N, independent per week). Replace 'core_action' with the value event.
-- Cohort = the person's first active week WITHIN the analysis window (the standard retention convention),
-- not their first-ever week. Widen the window, or anchor on a true first-seen week, if you need lifetime cohorts.
WITH activity AS (
    SELECT
        person_id,
        toStartOfWeek(timestamp) AS week
    FROM events
    WHERE event = 'core_action'
      AND timestamp >= now() - INTERVAL 12 WEEK
    GROUP BY person_id, week
),
cohort AS (
    SELECT person_id, min(week) AS cohort_week
    FROM activity
    GROUP BY person_id
)
SELECT
    c.cohort_week                                                    AS cohort_week,
    dateDiff('week', c.cohort_week, a.week)                          AS weeks_later,
    count(DISTINCT a.person_id)                                      AS retained,
    -- cohort size = retained at weeks_later = 0
    round(count(DISTINCT a.person_id)
          / max(count(DISTINCT a.person_id)) OVER (PARTITION BY c.cohort_week), 4) AS retention_rate
FROM cohort AS c
INNER JOIN activity AS a ON a.person_id = c.person_id
WHERE a.week >= c.cohort_week
GROUP BY cohort_week, weeks_later
ORDER BY cohort_week, weeks_later
