-- Funnel conversion with a fixed conversion window, using ClickHouse windowFunnel.
-- windowFunnel(window_seconds)(timestamp, cond1, cond2, ...) returns the count of steps completed IN ORDER
-- within window_seconds of the first step, per aggregation unit.
--
-- NOTE: wrap the time arg in toDateTime() — PostHog's `timestamp` is DateTime64, which windowFunnel rejects.
-- Replace the event names with the real ones (confirm via read-data-schema first).
-- Here: signed_up -> activated -> purchased, 14-day window (1209600s), per person.
WITH per_person AS (
    SELECT
        person_id,
        windowFunnel(1209600)(
            toDateTime(timestamp),
            event = 'signed_up',
            event = 'activated',
            event = 'purchased'
        ) AS steps_completed
    FROM events
    WHERE event IN ('signed_up', 'activated', 'purchased')
      AND timestamp >= now() - INTERVAL 90 DAY
    GROUP BY person_id
)
SELECT
    countIf(steps_completed >= 1)                                            AS entered_step_1,
    countIf(steps_completed >= 2)                                            AS reached_step_2,
    countIf(steps_completed >= 3)                                            AS reached_step_3,
    round(countIf(steps_completed >= 3) / nullif(countIf(steps_completed >= 1), 0), 4) AS overall_conversion,
    round(countIf(steps_completed >= 2) / nullif(countIf(steps_completed >= 1), 0), 4) AS step1_to_step2,
    round(countIf(steps_completed >= 3) / nullif(countIf(steps_completed >= 2), 0), 4) AS step2_to_step3
FROM per_person
