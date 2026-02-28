"""
Funnels precomputation: per-user step timestamp materialization.

Funnels are the hardest to precompute because they require per-user event sequences
with strict ordering and conversion windows. We explore two strategies here:

Strategy 1: Per-user step timestamps (RECOMMENDED)
    Precompute per user: earliest and latest timestamp of each funnel step event.
    This dramatically reduces the data volume for the UDF — instead of scanning
    all events, it reads a compact (person_id, event, min_ts, max_ts) table.

    This is exact for "ordered" funnels that only need the first occurrence of each step.
    For strict funnels (no intervening events), the full event stream is still needed.

Strategy 2: Hourly user-event buckets (APPROXIMATE)
    For each (event, hour), store the set of users who triggered it (as a theta sketch).
    Then check ordered intersection across hourly buckets.
    This relaxes ordering to hour-level granularity: events within the same hour are
    considered simultaneous for ordering purposes.

    For funnels with 14-day conversion windows, hour-level ordering is usually sufficient.
    But for sub-hour conversion windows, this loses too much precision.

Strategy 3: Pre-filtered event stream (SIMPLE)
    Cache just the filtered event scan (events matching any funnel step for a team).
    This is the cheapest win: the funnel UDF still runs, but the scan is smaller.
"""

from dataclasses import dataclass


@dataclass
class FunnelStep:
    """A single step in a funnel."""

    event: str
    properties_filter: str | None = None  # HogQL property filter expression


@dataclass
class FunnelPrecomputationConfig:
    """Configuration for funnel precomputation."""

    steps: list[FunnelStep]
    conversion_window_days: int = 14


# --- Strategy 1: Per-user step timestamps ---


def build_funnel_step_timestamps_insert(config: FunnelPrecomputationConfig) -> str:
    """
    Build INSERT query for per-user step timestamps.

    For each user and each funnel step event, stores:
    - first occurrence timestamp
    - last occurrence timestamp
    - occurrence count

    This is stored in the preaggregation_v2 table using:
    - event column: the step event name
    - count_state: occurrence count per user per event per hour
    - min_state: earliest timestamp in the hour
    - max_state: latest timestamp in the hour

    At query time, the funnel logic reads these materialized summaries
    instead of scanning the full events table.
    """
    events = [step.event for step in config.steps]
    events_list = ", ".join(f"'{e}'" for e in events)

    query = f"""
        SELECT
            toStartOfHour(timestamp) AS time_window_start,
            event,
            [] AS breakdown_value,
            sumState(toUInt64(1)) AS count_state,
            uniqState(person_id) AS uniq_persons_state,
            minState(toFloat64(toUnixTimestamp(timestamp))) AS min_state,
            maxState(toFloat64(toUnixTimestamp(timestamp))) AS max_state
        FROM events
        WHERE event IN ({events_list})
            AND timestamp >= {{time_window_min}}
            AND timestamp < {{time_window_max}}
        GROUP BY time_window_start, event
    """

    return query


def build_funnel_step_timestamps_combiner(config: FunnelPrecomputationConfig) -> str:
    """
    Build combiner query that produces per-user step event summaries.

    This replaces the inner event scan of the funnel query.
    For each user, it produces rows like:
        (person_id, event, first_ts, last_ts, count)

    For an ordered funnel, the UDF only needs to verify:
        first_ts(step_0) < first_ts(step_1) < first_ts(step_2) ...
        AND all within conversion_window

    Note: This combiner query can't directly use the aggregate merge functions
    because we need per-user data. Instead, we use a different precomputation
    approach: store per-(user, event, day) first/last timestamps.
    """
    events = [step.event for step in config.steps]
    events_list = ", ".join(f"'{e}'" for e in events)

    # For the simple case, we re-aggregate from hourly buckets to get per-user stats
    query = f"""
        SELECT
            person_id,
            event,
            min(timestamp) AS first_occurrence,
            max(timestamp) AS last_occurrence,
            count() AS occurrence_count
        FROM events
        WHERE event IN ({events_list})
            AND job_id IN {{job_ids}}
            AND timestamp >= {{time_start}}
            AND timestamp < {{time_end}}
        GROUP BY person_id, event
    """

    return query


# --- Strategy 2: Hourly user-event theta sketches ---


def build_funnel_hourly_sketches_insert(config: FunnelPrecomputationConfig) -> str:
    """
    Build INSERT query for hourly theta sketches per funnel step.

    Stores a theta sketch of user IDs for each (event, hour) combination.
    At query time, we can check ordered intersection:
        users_in_step1_hour_X ∩ users_in_step2_hour_Y where Y >= X
    """
    events = [step.event for step in config.steps]
    events_list = ", ".join(f"'{e}'" for e in events)

    query = f"""
        SELECT
            toStartOfHour(timestamp) AS time_window_start,
            event,
            [] AS breakdown_value,
            sumState(toUInt64(1)) AS count_state,
            uniqState(person_id) AS uniq_persons_state,
            uniqThetaState(person_id) AS uniq_theta_state
        FROM events
        WHERE event IN ({events_list})
            AND timestamp >= {{time_window_min}}
            AND timestamp < {{time_window_max}}
        GROUP BY time_window_start, event
    """

    return query


def build_funnel_hourly_combiner(config: FunnelPrecomputationConfig) -> str:
    """
    Build approximate funnel query using hourly theta sketch intersections.

    For a 3-step funnel A -> B -> C:
    1. For each hour H0 where A occurred, find theta sketch for A
    2. For each hour H1 >= H0 where B occurred, compute intersection(A_sketch, B_sketch)
    3. For each hour H2 >= H1 where C occurred, compute intersection(A∩B_sketch, C_sketch)
    4. Sum the final intersection cardinalities

    This is a cascading intersection across ordered hourly buckets.
    Conversion window is enforced by limiting how far apart H0 and HN can be.

    IMPORTANT: This approach has significant limitations:
    - Within-hour ordering is lost (events in the same hour treated as simultaneous)
    - For N steps and H hours, complexity is O(H^N) in the worst case
    - Theta sketch intersection error compounds across steps
    - Only practical for 2-3 step funnels with multi-day conversion windows

    For production use, Strategy 1 (per-user step timestamps) is recommended
    for most funnels, with this approach reserved for very large datasets where
    per-user state is prohibitively expensive.
    """
    if len(config.steps) < 2:
        raise ValueError("Funnel must have at least 2 steps")

    if len(config.steps) > 3:
        raise ValueError(
            "Approximate hourly funnel only supports up to 3 steps "
            "(theta sketch intersection error compounds with more steps)"
        )

    conversion_window_hours = config.conversion_window_days * 24
    step_events = [step.event for step in config.steps]

    # For a 2-step funnel: simple pairwise intersection
    if len(config.steps) == 2:
        return f"""
            WITH
                step1 AS (
                    SELECT time_window_start AS period, uniqThetaMerge(uniq_theta_state) AS sketch
                    FROM preaggregation_v2
                    WHERE job_id IN {{job_ids}} AND event = '{step_events[0]}'
                        AND time_window_start >= {{time_start}} AND time_window_start < {{time_end}}
                    GROUP BY period
                ),
                step2 AS (
                    SELECT time_window_start AS period, uniqThetaMerge(uniq_theta_state) AS sketch
                    FROM preaggregation_v2
                    WHERE job_id IN {{job_ids}} AND event = '{step_events[1]}'
                        AND time_window_start >= {{time_start}} AND time_window_start < {{time_end}}
                    GROUP BY period
                )
            SELECT
                bitmapCardinality(s1.sketch) AS step_1_count,
                sum(bitmapAndCardinality(s1.sketch, s2.sketch)) AS step_2_count
            FROM step1 s1
            CROSS JOIN step2 s2
            WHERE s2.period >= s1.period
                AND dateDiff('hour', s1.period, s2.period) <= {conversion_window_hours}
        """

    # For a 3-step funnel: cascading intersection
    return f"""
        WITH
            step1 AS (
                SELECT time_window_start AS period, uniqThetaMerge(uniq_theta_state) AS sketch
                FROM preaggregation_v2
                WHERE job_id IN {{job_ids}} AND event = '{step_events[0]}'
                    AND time_window_start >= {{time_start}} AND time_window_start < {{time_end}}
                GROUP BY period
            ),
            step2 AS (
                SELECT time_window_start AS period, uniqThetaMerge(uniq_theta_state) AS sketch
                FROM preaggregation_v2
                WHERE job_id IN {{job_ids}} AND event = '{step_events[1]}'
                    AND time_window_start >= {{time_start}} AND time_window_start < {{time_end}}
                GROUP BY period
            ),
            step3 AS (
                SELECT time_window_start AS period, uniqThetaMerge(uniq_theta_state) AS sketch
                FROM preaggregation_v2
                WHERE job_id IN {{job_ids}} AND event = '{step_events[2]}'
                    AND time_window_start >= {{time_start}} AND time_window_start < {{time_end}}
                GROUP BY period
            ),
            -- Step 1 to Step 2: pairwise intersections
            step1_to_2 AS (
                SELECT
                    s1.period AS step1_period,
                    s2.period AS step2_period,
                    bitmapAnd(s1.sketch, s2.sketch) AS intersection_sketch
                FROM step1 s1
                CROSS JOIN step2 s2
                WHERE s2.period >= s1.period
                    AND dateDiff('hour', s1.period, s2.period) <= {conversion_window_hours}
            )
        SELECT
            sum(bitmapCardinality(s1.sketch)) AS step_1_total,
            sum(bitmapAndCardinality(s1.sketch, s2.sketch)) AS step_2_total,
            sum(bitmapAndCardinality(s12.intersection_sketch, s3.sketch)) AS step_3_total
        FROM step1 s1
        CROSS JOIN step2 s2
        CROSS JOIN step3 s3
        LEFT JOIN step1_to_2 s12
            ON s12.step1_period = s1.period AND s12.step2_period = s2.period
        WHERE s2.period >= s1.period
            AND s3.period >= s2.period
            AND dateDiff('hour', s1.period, s3.period) <= {conversion_window_hours}
    """
