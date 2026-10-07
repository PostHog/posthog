-- Lifecycle: classify each person's weekly activity as new / returning / resurrecting, and count dormant.
-- Mirrors query-lifecycle: "new" means the person profile was created in that week, not the first event
-- in the window. Personless events are excluded, because lifecycle needs a person profile.
-- Reports 12 weeks, including the current week. The activity query reads one more week as a lookback,
-- so the first reported week can be classified as returning.
WITH activity AS (
    SELECT DISTINCT
        person_id,
        toStartOfWeek(timestamp)         AS week,
        toStartOfWeek(person.created_at) AS created_week
    FROM events
    WHERE event = 'core_action'
      AND properties.$process_person_profile != 'false'
      AND timestamp >= toStartOfWeek(now()) - INTERVAL 12 WEEK
      AND timestamp < toStartOfWeek(now()) + INTERVAL 1 WEEK
),
enriched AS (
    SELECT
        person_id,
        week,
        created_week,
        lagInFrame(week) OVER (PARTITION BY person_id ORDER BY week
                               ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS prev_week
    FROM activity
)
SELECT
    week,
    countIf(week = created_week)                                                          AS new,
    countIf(week != created_week AND prev_week = week - INTERVAL 1 WEEK)                  AS returning,
    countIf(week != created_week AND (prev_week IS NULL OR prev_week < week - INTERVAL 1 WEEK)) AS resurrecting
FROM enriched
WHERE week >= toStartOfWeek(now()) - INTERVAL 11 WEEK
GROUP BY week
ORDER BY week
-- A person whose profile was created in an earlier week than their first qualifying event shows as
-- resurrecting in that week, as in the native insight.
-- Dormant (users active the prior week but not this week) is derived from the gaps; compute it as a
-- negative series in the consuming view/insight, or with a symmetric self-anti-join if you need it inline.
