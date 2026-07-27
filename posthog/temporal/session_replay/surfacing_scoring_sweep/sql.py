"""ClickHouse statements for the session surfacing scoring pipeline.

The serving SELECT mirrors the training query in four CTEs:

    1. `eligible_sessions`: hash-partitioned slice of unscored, eventful sessions
       (`HAVING max(surfacing_score) IS NULL AND sum(event_count) > 0`) from
       `session_replay_events`.
       It carries `distinct_id` and `min_first_timestamp` to the producer
       because the partial-row Kafka writeback must reuse the real distinct_id
       (the `sipHash64(distinct_id)` shard key) and session-start timestamp
       (+1µs), or the AggregatingMergeTree can't merge the score onto the
       existing session row.
    2. `aggregated_sufficient_statistics`: raw aggregates from
       `session_replay_features`, filtered via `(team_id, session_id) GLOBAL IN`
       (each shard scans only its local rows) with the same lookback as training.
    3. `replay_features`: derives the trained rates/ratios; carries `team_id`
       so the final join shares a primary-key prefix and can't cross tenants.
    4. Final SELECT: inner-joins on `(team_id, session_id)`; sessions without
       features stay NULL and re-appear next tick until they age out of lookback.

CTE evaluation note: ClickHouse inlines `WITH ... AS` as a subquery, so
`eligible_sessions` is evaluated twice (GLOBAL IN, then final FROM). The
`ORDER BY session_id` before the LIMIT keeps the two evaluations consistent;
without it the inner join silently drops the mismatch.

Score writeback reuses the replay-ingestion Kafka topic (one JSONEachRow
message per session), the same pattern as the AI-summary writeback: the MV
does a partial-column insert and the AggregatingMergeTree merges
`max(surfacing_score)` onto the existing row.

Feature alignment contract: the final SELECT alias list must match the
booster's `feature_names` exactly (set + order). `feature_columns_in_select`
extracts it so `test_sql_alignment.py` asserts parity at CI and worker boot
re-asserts against the S3 booster. Drift silently mis-scores sessions.
"""

import re

# Distributed table names — hardcoded because there are no shared Python
# helpers in the codebase that re-export them. Source of truth lives in
# `posthog/session_recordings/sql/session_replay_event_sql.py` and
# `posthog/session_recordings/sql/session_replay_feature_sql.py`.
SESSION_REPLAY_EVENTS_TABLE = "session_replay_events"
SESSION_REPLAY_FEATURES_TABLE = "session_replay_features"


# --------------------------------------------------------------------------- #
# Aggregate fragment over `session_replay_features`.                           #
# Identical column-by-column to the training query's CTE.                      #
# --------------------------------------------------------------------------- #
_AGGREGATED_STATS_FRAGMENT = """
SELECT
    f.team_id,
    f.session_id,
    dateDiff('second', min(f.min_first_timestamp), max(f.max_last_timestamp)) AS session_duration_s,
    sum(f.event_count)                              AS event_count,
    sum(f.click_count)                              AS click_count,
    sum(f.keypress_count)                           AS keypress_count,
    sum(f.mouse_activity_count)                     AS mouse_activity_count,
    sum(f.rage_click_count)                         AS rage_click_count,
    sum(f.dead_click_count)                         AS dead_click_count,
    sum(f.quick_back_count)                         AS quick_back_count,
    sum(f.page_visit_count)                         AS page_visit_count,
    sum(f.text_selection_count)                     AS text_selection_count,
    sum(f.scroll_event_count)                       AS scroll_event_count,
    sum(f.console_error_count)                      AS console_error_count,
    sum(f.console_error_after_click_count)          AS console_error_after_click_count,
    sum(f.network_request_count)                    AS network_request_count,
    sum(f.network_failed_request_count)             AS network_failed_request_count,
    sum(f.mouse_position_count)                     AS mouse_position_count,
    sum(f.mouse_sum_x)                              AS mouse_sum_x,
    sum(f.mouse_sum_x_squared)                      AS mouse_sum_x_squared,
    sum(f.mouse_sum_y)                              AS mouse_sum_y,
    sum(f.mouse_sum_y_squared)                      AS mouse_sum_y_squared,
    sum(f.mouse_distance_traveled)                  AS mouse_distance_traveled,
    sum(f.mouse_direction_change_count)             AS mouse_direction_change_count,
    sum(f.mouse_velocity_sum)                       AS mouse_velocity_sum,
    sum(f.mouse_velocity_sum_of_squares)            AS mouse_velocity_sum_of_squares,
    sum(f.mouse_velocity_count)                     AS mouse_velocity_count,
    sum(f.total_scroll_magnitude)                   AS total_scroll_magnitude,
    sum(f.scroll_direction_reversal_count)          AS scroll_direction_reversal_count,
    sum(f.rapid_scroll_reversal_count)              AS rapid_scroll_reversal_count,
    max(f.max_scroll_y)                             AS max_scroll_y,
    sum(f.inter_action_gap_count)                   AS inter_action_gap_count,
    sum(f.inter_action_gap_sum_ms)                  AS inter_action_gap_sum_ms,
    sum(f.inter_action_gap_sum_of_squares_ms)       AS inter_action_gap_sum_of_squares_ms,
    max(f.max_idle_gap_ms)                          AS max_idle_gap_ms,
    sum(f.network_request_duration_sum)             AS network_request_duration_sum,
    sum(f.network_request_duration_sum_of_squares)  AS network_request_duration_sum_of_squares,
    sum(f.network_request_duration_count)           AS network_request_duration_count,
    sum(f.scroll_to_top_count)                      AS scroll_to_top_count,
    sum(f.backspace_count)                          AS backspace_count,
    sum(f.long_idle_gap_count)                      AS long_idle_gap_count,
    sum(f.console_warn_count)                       AS console_warn_count,
    sum(f.network_4xx_count)                        AS network_4xx_count,
    sum(f.network_5xx_count)                        AS network_5xx_count,
    sum(f.mutation_count)                           AS mutation_count,
    sum(f.viewport_resize_count)                    AS viewport_resize_count,
    sum(f.touch_event_count)                        AS touch_event_count,
    sum(f.selection_copy_count)                     AS selection_copy_count,
    sum(f.login_path_visit_count)                   AS login_path_visit_count,
    sum(f.signup_path_visit_count)                  AS signup_path_visit_count,
    sum(f.checkout_path_visit_count)                AS checkout_path_visit_count,
    sum(f.cart_path_visit_count)                    AS cart_path_visit_count,
    sum(f.billing_path_visit_count)                 AS billing_path_visit_count,
    sum(f.settings_path_visit_count)                AS settings_path_visit_count,
    sum(f.account_path_visit_count)                 AS account_path_visit_count,
    sum(f.error_path_visit_count)                   AS error_path_visit_count,
    sum(f.not_found_path_visit_count)               AS not_found_path_visit_count,
    sum(f.admin_path_visit_count)                   AS admin_path_visit_count,
    sum(f.dashboard_path_visit_count)               AS dashboard_path_visit_count,
    sum(f.onboarding_path_visit_count)              AS onboarding_path_visit_count,
    sum(f.cancel_path_visit_count)                  AS cancel_path_visit_count,
    sum(f.refund_path_visit_count)                  AS refund_path_visit_count,
    uniqCombinedMerge(12)(f.unique_url_count)          AS unique_urls,
    uniqCombinedMerge(12)(f.unique_click_target_count) AS unique_click_targets,
    uniqCombinedMerge(12)(f.unique_form_field_count)   AS unique_form_fields
FROM {features_table} AS f
WHERE (f.team_id, f.session_id) GLOBAL IN (SELECT team_id, session_id FROM eligible_sessions)
  AND f.min_first_timestamp >= now() - toIntervalDay(%(lookback_days)s)
GROUP BY f.team_id, f.session_id
""".strip()


# --------------------------------------------------------------------------- #
# Derived feature fragment over the aggregated stats CTE.                      #
# Identical column-by-column to the training query's `replay_features` CTE.    #
# --------------------------------------------------------------------------- #
_REPLAY_FEATURES_FRAGMENT = """
SELECT
    f.team_id,
    f.session_id,
    f.event_count                          / nullIf(f.session_duration_s, 0) AS event_rate,
    f.click_count                          / nullIf(f.session_duration_s, 0) AS click_rate,
    f.keypress_count                       / nullIf(f.session_duration_s, 0) AS keypress_rate,
    f.mouse_activity_count                 / nullIf(f.session_duration_s, 0) AS mouse_activity_rate,
    f.rage_click_count                     / nullIf(f.session_duration_s, 0) AS rage_click_rate,
    f.dead_click_count                     / nullIf(f.session_duration_s, 0) AS dead_click_rate,
    f.quick_back_count                     / nullIf(f.session_duration_s, 0) AS quick_back_rate,
    f.page_visit_count                     / nullIf(f.session_duration_s, 0) AS page_visit_rate,
    f.text_selection_count                 / nullIf(f.session_duration_s, 0) AS text_selection_rate,
    f.scroll_event_count                   / nullIf(f.session_duration_s, 0) AS scroll_event_rate,
    f.console_error_count                  / nullIf(f.session_duration_s, 0) AS console_error_rate,
    f.console_error_after_click_count      / nullIf(f.session_duration_s, 0) AS console_error_after_click_rate,
    f.network_request_count                / nullIf(f.session_duration_s, 0) AS network_request_rate,
    f.network_failed_request_count         / nullIf(f.session_duration_s, 0) AS network_failed_request_rate,
    f.mouse_sum_x / nullIf(f.mouse_position_count, 0) AS mouse_mean_x,
    f.mouse_sum_y / nullIf(f.mouse_position_count, 0) AS mouse_mean_y,
    sqrt(greatest(0, f.mouse_sum_x_squared / nullIf(f.mouse_position_count, 0)
                  - pow(f.mouse_sum_x   / nullIf(f.mouse_position_count, 0), 2))) AS mouse_stddev_x,
    sqrt(greatest(0, f.mouse_sum_y_squared / nullIf(f.mouse_position_count, 0)
                  - pow(f.mouse_sum_y   / nullIf(f.mouse_position_count, 0), 2))) AS mouse_stddev_y,
    f.mouse_distance_traveled              / nullIf(f.session_duration_s, 0)         AS mouse_distance_per_s,
    f.mouse_direction_change_count         / nullIf(f.mouse_distance_traveled, 0)    AS mouse_direction_change_rate,
    f.mouse_velocity_sum / nullIf(f.mouse_velocity_count, 0) AS mouse_velocity_mean,
    sqrt(greatest(0, f.mouse_velocity_sum_of_squares / nullIf(f.mouse_velocity_count, 0)
                  - pow(f.mouse_velocity_sum     / nullIf(f.mouse_velocity_count, 0), 2))) AS mouse_velocity_stddev,
    f.total_scroll_magnitude               / nullIf(f.session_duration_s, 0)  AS scroll_magnitude_per_s,
    f.total_scroll_magnitude               / nullIf(f.scroll_event_count, 0)  AS scroll_magnitude_per_event,
    f.scroll_direction_reversal_count      / nullIf(f.session_duration_s, 0)  AS scroll_direction_reversal_rate,
    f.rapid_scroll_reversal_count          / nullIf(f.session_duration_s, 0)  AS rapid_scroll_reversal_rate,
    f.max_scroll_y,
    f.inter_action_gap_sum_ms              / nullIf(f.inter_action_gap_count, 0) AS inter_action_gap_mean_ms,
    sqrt(greatest(0, f.inter_action_gap_sum_of_squares_ms / nullIf(f.inter_action_gap_count, 0)
                  - pow(f.inter_action_gap_sum_ms     / nullIf(f.inter_action_gap_count, 0), 2))) AS inter_action_gap_stddev_ms,
    f.max_idle_gap_ms,
    f.network_request_duration_sum / nullIf(f.network_request_duration_count, 0) AS network_request_duration_mean_ms,
    sqrt(greatest(0, f.network_request_duration_sum_of_squares / nullIf(f.network_request_duration_count, 0)
                  - pow(f.network_request_duration_sum     / nullIf(f.network_request_duration_count, 0), 2))) AS network_request_duration_stddev_ms,
    f.network_failed_request_count / nullIf(f.network_request_count, 0)          AS network_failure_ratio,
    f.network_4xx_count            / nullIf(f.network_request_count, 0)          AS network_4xx_ratio,
    f.network_5xx_count            / nullIf(f.network_request_count, 0)          AS network_5xx_ratio,
    f.scroll_to_top_count          / nullIf(f.session_duration_s, 0)             AS scroll_to_top_rate,
    f.backspace_count              / nullIf(f.keypress_count, 0)                 AS backspace_ratio,
    f.long_idle_gap_count          / nullIf(f.inter_action_gap_count, 0)         AS long_idle_gap_share,
    f.console_warn_count           / nullIf(f.session_duration_s, 0)             AS console_warn_rate,
    f.mutation_count               / nullIf(f.session_duration_s, 0)             AS mutation_rate,
    f.viewport_resize_count,
    f.touch_event_count            / nullIf(f.session_duration_s, 0)             AS touch_event_rate,
    f.selection_copy_count,
    f.login_path_visit_count       / nullIf(f.page_visit_count, 0)               AS login_path_visit_share,
    f.signup_path_visit_count      / nullIf(f.page_visit_count, 0)               AS signup_path_visit_share,
    f.checkout_path_visit_count    / nullIf(f.page_visit_count, 0)               AS checkout_path_visit_share,
    f.cart_path_visit_count        / nullIf(f.page_visit_count, 0)               AS cart_path_visit_share,
    f.billing_path_visit_count     / nullIf(f.page_visit_count, 0)               AS billing_path_visit_share,
    f.settings_path_visit_count    / nullIf(f.page_visit_count, 0)               AS settings_path_visit_share,
    f.account_path_visit_count     / nullIf(f.page_visit_count, 0)               AS account_path_visit_share,
    f.error_path_visit_count       / nullIf(f.page_visit_count, 0)               AS error_path_visit_share,
    f.not_found_path_visit_count   / nullIf(f.page_visit_count, 0)               AS not_found_path_visit_share,
    f.admin_path_visit_count       / nullIf(f.page_visit_count, 0)               AS admin_path_visit_share,
    f.dashboard_path_visit_count   / nullIf(f.page_visit_count, 0)               AS dashboard_path_visit_share,
    f.onboarding_path_visit_count  / nullIf(f.page_visit_count, 0)               AS onboarding_path_visit_share,
    f.cancel_path_visit_count      / nullIf(f.page_visit_count, 0)               AS cancel_path_visit_share,
    f.refund_path_visit_count      / nullIf(f.page_visit_count, 0)               AS refund_path_visit_share,
    f.unique_urls                  / nullIf(f.page_visit_count, 0)               AS unique_url_share,
    f.unique_click_targets         / nullIf(f.click_count, 0)                    AS click_target_share,
    f.unique_form_fields,
    greatest(0, f.page_visit_count - f.unique_urls) / nullIf(f.page_visit_count, 0) AS page_revisit_share,
    f.unique_urls                  AS unique_urls,
    f.unique_click_targets         AS unique_click_targets,
    greatest(0, f.page_visit_count - f.unique_urls)                              AS page_revisit_count
FROM aggregated_sufficient_statistics f
""".strip()


def fetch_features_sql(
    replay_events_table: str = SESSION_REPLAY_EVENTS_TABLE,
    features_table: str = SESSION_REPLAY_FEATURES_TABLE,
) -> str:
    """Return the parameterized SELECT used by `score_chunk_activity`.

    Bound parameters: %(of_chunks)s, %(chunk_id)s, %(lookback_days)s, %(chunk_size)s.

    Returned columns: `team_id`, `session_id`, `distinct_id`, `min_first_timestamp`,
    then the feature columns. The feature alias list must match the booster's
    `feature_names` (= `scorer.get_feature_names()`); `validate_features`
    enforces this on every chunk. Row count <= chunk_size, minus any
    sessions that have no replay features (inner-joined out).

    `distinct_id` and `min_first_timestamp` are surfaced specifically so the
    writeback can build an identity-value Kafka payload that (a) routes to
    the right shard via the sipHash64(distinct_id) sharding key and (b)
    cannot corrupt min/max/argMin aggregates on the existing session rows.
    """
    return f"""
WITH eligible_sessions AS (
    SELECT
        team_id,
        session_id,
        any(distinct_id) AS distinct_id,
        -- Aliased away from the raw column name: CH expands a same-named
        -- SELECT alias into WHERE, which would turn the raw-row prefilter
        -- below into an illegal aggregate-in-WHERE.
        min(min_first_timestamp) AS started_at
    FROM {replay_events_table}
    -- Raw-row prefilter with a +1 day buffer so the scan prunes on the
    -- min_first_timestamp ordering key instead of aggregating the whole
    -- table. The exact lookback cut stays in HAVING on the aggregated min;
    -- the buffer keeps the HAVING result identical for any session whose
    -- rows span less than a day.
    WHERE cityHash64(session_id) %% %(of_chunks)s = %(chunk_id)s
      AND min_first_timestamp >= now() - toIntervalDay(%(lookback_days)s + 1)
    GROUP BY team_id, session_id
    HAVING max(surfacing_score) IS NULL
      AND started_at >= now() - toIntervalDay(%(lookback_days)s)
      -- Eventless sessions have no features, so the inner join always drops them;
      -- excluding them here stops them starving the LIMIT and being re-picked every tick.
      AND sum(event_count) > 0
    -- ORDER BY makes LIMIT deterministic across the two CTE evaluations
    -- (CH inlines CTEs as subqueries — without a stable order, the GLOBAL IN
    -- subquery and the final FROM could pick different subsets and the
    -- inner join would silently drop the difference).
    ORDER BY session_id
    LIMIT %(chunk_size)s
),
aggregated_sufficient_statistics AS (
    {_AGGREGATED_STATS_FRAGMENT.format(features_table=features_table)}
),
replay_features AS (
    {_REPLAY_FEATURES_FRAGMENT}
)
SELECT
    e.team_id,
    e.session_id,
    e.distinct_id,
    e.started_at AS min_first_timestamp,
    rf.event_rate,
    rf.click_rate,
    rf.keypress_rate,
    rf.mouse_activity_rate,
    rf.rage_click_rate,
    rf.dead_click_rate,
    rf.quick_back_rate,
    rf.page_visit_rate,
    rf.text_selection_rate,
    rf.scroll_event_rate,
    rf.console_error_rate,
    rf.console_error_after_click_rate,
    rf.network_request_rate,
    rf.network_failed_request_rate,
    rf.mouse_mean_x,
    rf.mouse_mean_y,
    rf.mouse_stddev_x,
    rf.mouse_stddev_y,
    rf.mouse_distance_per_s,
    rf.mouse_direction_change_rate,
    rf.mouse_velocity_mean,
    rf.mouse_velocity_stddev,
    rf.scroll_magnitude_per_s,
    rf.scroll_magnitude_per_event,
    rf.scroll_direction_reversal_rate,
    rf.rapid_scroll_reversal_rate,
    rf.max_scroll_y,
    rf.inter_action_gap_mean_ms,
    rf.inter_action_gap_stddev_ms,
    rf.max_idle_gap_ms,
    rf.network_request_duration_mean_ms,
    rf.network_request_duration_stddev_ms,
    rf.network_failure_ratio,
    rf.network_4xx_ratio,
    rf.network_5xx_ratio,
    rf.scroll_to_top_rate,
    rf.backspace_ratio,
    rf.long_idle_gap_share,
    rf.console_warn_rate,
    rf.mutation_rate,
    rf.viewport_resize_count,
    rf.touch_event_rate,
    rf.selection_copy_count,
    rf.login_path_visit_share,
    rf.signup_path_visit_share,
    rf.checkout_path_visit_share,
    rf.cart_path_visit_share,
    rf.billing_path_visit_share,
    rf.settings_path_visit_share,
    rf.account_path_visit_share,
    rf.error_path_visit_share,
    rf.not_found_path_visit_share,
    rf.admin_path_visit_share,
    rf.dashboard_path_visit_share,
    rf.onboarding_path_visit_share,
    rf.cancel_path_visit_share,
    rf.refund_path_visit_share,
    rf.unique_url_share,
    rf.click_target_share,
    rf.unique_form_fields,
    rf.page_revisit_share,
    -- Raw counts the current production booster consumes directly. The richer
    -- query keeps the share/ratio variants above; surfacing both lets a simpler
    -- booster (a subset of these columns) score against this superset query
    -- without retraining or a serving code change.
    rf.unique_urls,
    rf.unique_click_targets,
    rf.page_revisit_count
FROM eligible_sessions e
INNER JOIN replay_features rf ON rf.team_id = e.team_id AND rf.session_id = e.session_id
""".strip()


def count_unscored_sql(replay_events_table: str = SESSION_REPLAY_EVENTS_TABLE) -> str:
    """Return a cheap COUNT estimate of unscored sessions in one hash bucket.

    Bound parameters: %(lookback_days)s, %(of_chunks)s.

    Sampling one bucket and extrapolating (× of_chunks in the caller) is a
    cheap backlog estimate, far cheaper than scanning every unscored session.
    """
    return f"""
SELECT count()
FROM (
    SELECT session_id
    FROM {replay_events_table}
    -- Same raw-row prefilter as fetch_features_sql — see comment there.
    WHERE cityHash64(session_id) %% %(of_chunks)s = 0
      AND min_first_timestamp >= now() - toIntervalDay(%(lookback_days)s + 1)
    GROUP BY team_id, session_id
    HAVING max(surfacing_score) IS NULL
      AND min(min_first_timestamp) >= now() - toIntervalDay(%(lookback_days)s)
      -- Match fetch_features_sql: eventless sessions aren't scorable backlog.
      AND sum(event_count) > 0
)
""".strip()


# --------------------------------------------------------------------------- #
# Feature-alignment helper                                                     #
# --------------------------------------------------------------------------- #

# Matches an `<alias>.<column>` line in the final SELECT (optional trailing
# comma). The alias is `e` for ID columns or `rf` for features; the caller
# filters by alias.
_SELECT_ALIAS_RE = re.compile(r"^\s*(\w+)\.(\w+)\s*,?\s*$", re.MULTILINE)


def feature_columns_in_select(sql: str, *, feature_table_alias: str = "rf") -> tuple[str, ...]:
    """Return the ordered tuple of feature column aliases from the final SELECT.

    Backs the SQL/booster parity test in `test_sql_alignment.py`: drift from
    the booster's `feature_names` silently mis-scores sessions, so the test
    catches it at CI. Returns the empty tuple on a malformed final SELECT
    (the caller treats that as a hard fail).
    """
    # Anchor on the final `)SELECT ... FROM` so we don't pick up `<alias>.<col>`
    # references inside earlier CTEs' ON clauses or aggregate args.
    final_select = re.search(
        r"\)\s*SELECT\b(?P<body>.*?)\bFROM\s+eligible_sessions\b",
        sql,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not final_select:
        return ()
    body = final_select.group("body")
    return tuple(name for alias, name in _SELECT_ALIAS_RE.findall(body) if alias == feature_table_alias)
