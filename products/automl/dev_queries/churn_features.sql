-- Biweekly churn prediction features, rolled up to person_id, split and avoiding feature leakage
--
-- For training we anchor the prediction moment 14 days in the past so the
-- 14-day target window has already elapsed and is observable:
--
--   Past / feature window:  [now-60d, now-14d]   up to 46 days of history
--   Cutoff:                 now() - 14 days       (the "today" anchor)
--   Future / target window: (now-14d, now]        14 days of outcome
--
-- Population: persons who fired at least one $identify event in the past
-- window. Filter lives in HAVING rather than WHERE — putting
-- `person.properties.email` in WHERE forced a per-row JOIN against the
-- persons table which was the dominant scan cost. The identify-event proxy
-- catches actively-identifying users without the JOIN.
--
-- Memory-saving choices (in order of impact):
--   * HAVING `identify_events_pre > 0` — identified-user filter post-aggregation
--     (the WHERE-side `person.properties.email` variant forced a per-row
--     persons JOIN which dominated scan cost on large events tables).
--   * `event IN (...)` allowlist — ClickHouse skips rows whose event name
--     isn't used by any feature. If you add a feature that references a
--     new event name, add it below.
--   * `cityHash64(...) % 10000 < {sample_threshold}` — person sample.
--     Pass `--sample-pct N` (float, default 10). Lower to tighten memory
--     further; floats like 0.5 or 0.01 are supported.
--   * `uniqIf(value, cond)` replaces `count(DISTINCT if(cond, value, NULL))`
--     for approximate-but-cheap distinct counts (HyperLogLog).

SELECT
    toString(person_id) AS user_id,
    -- ---- Activity volume in the past window ----
    countIf(timestamp <= now() - INTERVAL 14 DAY)                                                      AS events_pre,
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event = '$pageview')                              AS pageviews_pre,
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event = '$pageleave')                             AS pageleaves_pre,
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event = '$autocapture')                           AS autocaptures_pre,
    -- Property-based sub-features disabled for performance — they force JSON
    -- extraction on every $autocapture row. Uncomment to re-enable individually.
    -- countIf(timestamp <= now() - INTERVAL 14 DAY AND event = '$autocapture' AND properties.$event_type = 'click')  AS clicks_pre,
    -- countIf(timestamp <= now() - INTERVAL 14 DAY AND event = '$autocapture' AND properties.$event_type = 'submit') AS submits_pre,
    -- countIf(timestamp <= now() - INTERVAL 14 DAY AND event = '$autocapture' AND properties.$event_type = 'change') AS changes_pre,
    uniqIf($session_id, timestamp <= now() - INTERVAL 14 DAY)                                          AS sessions_pre,
    uniqIf(toDate(timestamp), timestamp <= now() - INTERVAL 14 DAY)                                    AS active_days_pre,
    uniqIf(event, timestamp <= now() - INTERVAL 14 DAY)                                                AS distinct_event_types_pre,
    -- ---- Engagement quality ----
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event = '$copy_autocapture')                      AS copy_events_pre,
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event = '$identify')                              AS identify_events_pre,
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event IN ('$identify', 'signed in', 'logged in')) AS login_events_pre,
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event = '$opt_in')                                AS opt_ins_pre,
    -- ---- Friction / quality signals ----
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event = '$rageclick')                             AS rageclicks_pre,
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event = '$dead_click')                            AS dead_clicks_pre,
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event = '$exception')                             AS exceptions_pre,
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event = '$csp_violation')                         AS csp_violations_pre,
    -- ---- PostHog product breadth ----
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event = 'insight viewed')                         AS insight_views_pre,
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event = 'dashboard viewed')                       AS dashboard_views_pre,
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event = 'recording viewed')                       AS recording_views_pre,
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event = '$feature_flag_called')                   AS flag_evals_pre,
    -- Property-based distinct flag count disabled for performance — uniqIf on
    -- a JSON property forces extraction on every $feature_flag_called row.
    -- uniqIf(properties.$feature_flag, timestamp <= now() - INTERVAL 14 DAY AND event = '$feature_flag_called') AS distinct_flags_pre,
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event IN ('survey shown', 'survey sent', 'survey dismissed')) AS survey_events_pre,
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event = '$feature_enrollment_update')             AS early_access_optins_pre,
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event = '$ai_generation')                         AS llm_generations_pre,
    -- ---- Mobile / app signal ----
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event = '$screen')                                AS screen_views_pre,
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event = 'Application opened')                     AS app_opens_pre,
    countIf(timestamp <= now() - INTERVAL 14 DAY AND event = 'Application backgrounded')               AS app_backgrounded_pre,
    -- ---- Recency / tenure measured at the cutoff (not "now") ----
    dateDiff('day', maxIf(timestamp, timestamp <= now() - INTERVAL 14 DAY), now() - INTERVAL 14 DAY)    AS last_active_days_ago_at_cutoff,
    dateDiff('day', minIf(timestamp, timestamp <= now() - INTERVAL 14 DAY), now() - INTERVAL 14 DAY)    AS first_seen_days_ago_at_cutoff,
    -- ---- Target: any allowlisted event in the future window? ----
    -- (The allowlist covers every active-user signal — $pageview, $autocapture,
    --  $identify, $screen, Application opened — so this is effectively "any
    --  meaningful activity in the next 14 days".)
    if(countIf(timestamp > now() - INTERVAL 14 DAY) = 0, 1, 0)                                         AS churned
FROM events
WHERE timestamp > now() - INTERVAL 60 DAY
  AND person_id IS NOT NULL
  -- Identification filter moved to HAVING (`identify_events_pre > 0`).
  -- Putting `person.properties.X` in WHERE forced a per-row JOIN against
  -- the persons table + JSON extraction — dominant scan cost on large
  -- events tables. Post-aggregation filter is much cheaper.
  -- {sample_threshold} = round(sample_pct * 100). Divisor of 10000 gives
  -- 4-decimal sample resolution, so floats down to 0.01% work cleanly.
  AND cityHash64(toString(person_id)) % 10000 < {sample_threshold}
  AND event IN (
      '$pageview', '$pageleave', '$autocapture',
      '$copy_autocapture', '$identify', '$opt_in',
      '$rageclick', '$dead_click', '$exception', '$csp_violation',
      'insight viewed', 'dashboard viewed', 'recording viewed',
      '$feature_flag_called',
      'survey shown', 'survey sent', 'survey dismissed',
      '$feature_enrollment_update', '$ai_generation',
      '$screen', 'Application opened', 'Application backgrounded',
      'signed in', 'logged in'
  )
GROUP BY person_id
HAVING events_pre > 0
   -- Identified-user proxy: had at least one $identify event in the past
   -- window. Captures most actively-identifying users; misses anyone who
   -- $identified > 70 days ago and hasn't re-fired since. Widen the WHERE
   -- date range if you need to catch older identifiers.
   AND identify_events_pre > 0
   -- Restrict to users who were recently active at the anchor moment.
   -- Without this, the training set is dominated by users who churned
   -- long ago (anyone with one event 50 days ago counts as "in the past
   -- 70-day window" but is guaranteed churned). Filtering by recency at
   -- the cutoff produces a healthy "at-risk" population for a churn model.
   AND last_active_days_ago_at_cutoff <= 21
LIMIT 1000000
