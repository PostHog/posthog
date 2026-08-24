-- Lifecycle: classify each person's weekly activity as new / returning / resurrecting, and count dormant.
-- Compares each active week to the person's previous active week and their first active week in the window.
-- Note: first_week is the earliest week WITHIN this window, so a user active just before it can show as
-- "new" at the window's left edge. Extend the window one interval earlier if that boundary matters.
WITH activity AS (
    SELECT DISTINCT
        person_id,
        toStartOfWeek(timestamp) AS week
    FROM events
    WHERE event = 'core_action'
      AND timestamp >= now() - INTERVAL 12 WEEK
),
enriched AS (
    SELECT
        person_id,
        week,
        min(week) OVER (PARTITION BY person_id)                                        AS first_week,
        lagInFrame(week) OVER (PARTITION BY person_id ORDER BY week
                               ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING) AS prev_week
    FROM activity
)
SELECT
    week,
    countIf(week = first_week)                                                          AS new,
    countIf(week != first_week AND prev_week = week - INTERVAL 1 WEEK)                  AS returning,
    countIf(week != first_week AND (prev_week IS NULL OR prev_week < week - INTERVAL 1 WEEK)) AS resurrecting
FROM enriched
GROUP BY week
ORDER BY week
-- Dormant (users active the prior week but not this week) is derived from the gaps; compute it as a
-- negative series in the consuming view/insight, or with a symmetric self-anti-join if you need it inline.
