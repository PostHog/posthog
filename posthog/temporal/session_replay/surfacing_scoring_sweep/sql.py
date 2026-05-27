"""ClickHouse statements for the session surfacing scoring pipeline.

The serving SELECT mirrors the training query:

    1. `eligible_sessions` — hash-partitioned slice of unscored sessions from
       `session_replay_events` (the table the score is written back to). It
       carries `team_id`, `session_id`, `distinct_id`, and `min_first_timestamp`
       through to the producer:

         * `team_id` + `session_id` join to `session_replay_features` and
           identify the row to score.
         * `distinct_id` is the Distributed sharding key
           (`sipHash64(distinct_id)`) on `writable_session_replay_events`. The
           partial-row Kafka writeback MUST carry the real distinct_id so the
           merged row lands on the same shard as the rest of the session;
           otherwise the AggregatingMergeTree can never combine them.
         * `min_first_timestamp` is the session-start timestamp the producer
           uses (+1µs) for the partial row, so min/max/argMin aggregations on
           the MV side still prefer the real session rows.

       `HAVING max(surfacing_score) IS NULL` is the unscored filter.
       `ORDER BY session_id LIMIT chunk_size` makes the chunk deterministic
       across the two CTE evaluations (see note below).

    2. `aggregated_sufficient_statistics` — pulls raw aggregates from
       `session_replay_features` for those sessions, mirroring the
       training query. We filter via `(team_id, session_id) GLOBAL IN ...`
       so the lookup hits the (team_id, session_id) primary key on
       `session_replay_features` for index-friendly granule skipping
       instead of a full partition scan, and `GLOBAL IN` ships the
       eligible-session set as a temp table to every shard so each shard
       only scans its locally-resident replay rows.

    3. `replay_features` — derives the rates/ratios/stats the model was
       trained on. Same expressions as the training query. Carries
       `team_id` through so the final join is on the same primary-key
       prefix and can't accidentally cross tenants.

    4. Final SELECT — joins `replay_features` back to `eligible_sessions`
       on `(team_id, session_id)` (inner join: sessions without replay
       features are dropped and stay NULL in session_replay_events — they
       re-appear on the next tick within the lookback window, then
       naturally fall out once they age past it).

CTE evaluation note: ClickHouse inlines `WITH ... AS` as a subquery — it
does not materialize the CTE once and reuse the result. `eligible_sessions`
is therefore evaluated twice (once for the GLOBAL IN subquery, once for
the final FROM). The `ORDER BY session_id` before the LIMIT is what
keeps the two evaluations consistent; without it, two un-ordered LIMITs
of the same query are not guaranteed to return the same rows, and any
mismatch would be silently dropped by the inner join.

Score writeback flows through the existing replay-ingestion Kafka topic
(`KAFKA_CLICKHOUSE_SESSION_REPLAY_EVENTS`) — same pattern as the AI-summary
writeback in `posthog.temporal.session_replay.session_summary.activities.
video_based.a7d_tag_and_highlight_session`. The activity emits one
JSONEachRow message per scored session with identity values for every
non-score column; `session_replay_events_mv` consumes via `Kafka` engine
and performs a partial-column insert into `writable_session_replay_events`.
The AggregatingMergeTree then merges `max(surfacing_score)` onto
the existing session row without disturbing any other aggregate.

Feature alignment contract: the final SELECT alias list must match the
booster's `feature_names` exactly (set + order). `feature_columns_in_select`
extracts the alias list so `test_sql_alignment.py` asserts parity against
`FEATURE_RANGES` at CI time; worker boot re-asserts against the S3 booster.
Drift = silently mis-scored sessions, so we catch it before runtime.
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
    greatest(0, f.page_visit_count - f.unique_urls) / nullIf(f.page_visit_count, 0) AS page_revisit_share
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
        min(min_first_timestamp) AS min_first_timestamp
    FROM {replay_events_table}
    WHERE cityHash64(session_id) %% %(of_chunks)s = %(chunk_id)s
    GROUP BY team_id, session_id
    HAVING max(surfacing_score) IS NULL
      AND min(min_first_timestamp) >= now() - toIntervalDay(%(lookback_days)s)
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
    e.min_first_timestamp,
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
    rf.page_revisit_share
FROM eligible_sessions e
INNER JOIN replay_features rf ON rf.team_id = e.team_id AND rf.session_id = e.session_id
""".strip()


def count_unscored_sql(replay_events_table: str = SESSION_REPLAY_EVENTS_TABLE) -> str:
    """Return a cheap COUNT estimate of unscored sessions in one hash bucket.

    Bound parameter: %(lookback_days)s, %(of_chunks)s.

    Sampling one bucket and extrapolating (multiply by `of_chunks` in the
    caller) is far cheaper than scanning all unscored sessions to decide
    whether to dispatch the tick.
    """
    return f"""
SELECT count()
FROM (
    SELECT session_id
    FROM {replay_events_table}
    WHERE cityHash64(session_id) %% %(of_chunks)s = 0
    GROUP BY team_id, session_id
    HAVING max(surfacing_score) IS NULL
      AND min(min_first_timestamp) >= now() - toIntervalDay(%(lookback_days)s)
)
""".strip()


# --------------------------------------------------------------------------- #
# Feature-alignment helper                                                     #
# --------------------------------------------------------------------------- #

# Matches a `<table_alias>.<column_name>` expression on its own line in the
# final SELECT (one column per line, optional trailing comma). The alias
# group `(\w+)` comes back as `e` for ID columns or `rf` for features —
# the caller filters by alias.
_SELECT_ALIAS_RE = re.compile(r"^\s*(\w+)\.(\w+)\s*,?\s*$", re.MULTILINE)


def feature_columns_in_select(sql: str, *, feature_table_alias: str = "rf") -> tuple[str, ...]:
    """Return the ordered tuple of feature column aliases from the final SELECT.

    Pure-string parser used by the SQL/booster parity test in
    `test_sql_alignment.py` — drift between this list and the booster's
    `feature_names` would silently mis-score sessions (validate_features
    would catch it at runtime, but the test catches it at CI before any
    deploy).

    Walks `fetch_features_sql()`'s output, extracts every line of the form
    `<feature_table_alias>.<name>` from after the last CTE close-paren, and
    returns them in source order. ID columns (alias `e.`) are ignored by
    matching only `feature_table_alias`. Returns the empty tuple if the
    final SELECT is malformed — the caller should treat that as a hard fail.
    """
    # Locate the body after the CTE block: everything from the final
    # `)\nSELECT` to the next `FROM`. Anchoring on the FROM keeps the parser
    # from accidentally picking up `<alias>.<col>` references that live in
    # ON clauses or aggregate args inside earlier CTEs.
    final_select = re.search(
        r"\)\s*SELECT\b(?P<body>.*?)\bFROM\s+eligible_sessions\b",
        sql,
        flags=re.DOTALL | re.IGNORECASE,
    )
    if not final_select:
        return ()
    body = final_select.group("body")
    return tuple(name for alias, name in _SELECT_ALIAS_RE.findall(body) if alias == feature_table_alias)
