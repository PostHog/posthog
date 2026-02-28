"""
Retention precomputation using theta sketches for set intersection.

Retention asks: "Of users who did event A in period X, how many did event B in period Y?"

The current implementation scans all events, groups by person, collects per-person
arrays of intervals, and then counts intersections. This is expensive because it
requires per-person state for the full time range.

Precomputation strategy: store per-(event, period) theta sketches of user sets.
Then at query time, use bitmap intersection to compute cohort retention:

  retention[cohort_period][return_period] = bitmapAndCardinality(
      cohort_sketch,   -- users who did start_event in cohort_period
      return_sketch    -- users who did return_event in return_period
  )

Theta sketches (uniqTheta in ClickHouse) support:
- Union: bitmapOr (equivalent to uniqMerge)
- Intersection: bitmapAnd (the key operation for retention)
- Difference: bitmapAndnot
- Cardinality: bitmapCardinality

Error rate is ~2%, same as uniq (HyperLogLog), but with set operations.

Trade-offs vs exact computation:
- ~2% error on intersection counts
- Ordering within a period is lost (hourly bucketing mitigates this)
- Much faster: no per-person state, just sketch merges
- Reusable: same sketches serve different retention configurations
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class RetentionPrecomputationConfig:
    """Configuration for retention precomputation."""

    start_event: str  # event that defines the cohort (e.g., "$pageview")
    return_event: str  # event that defines retention (e.g., same or different)
    interval: str = "day"  # "hour", "day", "week", "month"


# Interval → ClickHouse function
INTERVAL_FUNCTIONS: dict[str, str] = {
    "hour": "toStartOfHour",
    "day": "toStartOfDay",
    "week": "toStartOfWeek",
    "month": "toStartOfMonth",
}


def build_retention_insert_query(config: RetentionPrecomputationConfig) -> str:
    """
    Build the INSERT query for retention precomputation.

    Stores one theta sketch per (event, period). Both start and return events
    are precomputed in a single pass if they differ.

    The event column distinguishes start vs return event sketches.
    """
    interval_fn = INTERVAL_FUNCTIONS.get(config.interval, "toStartOfDay")

    events_filter_parts = [f"'{config.start_event}'"]
    if config.start_event != config.return_event:
        events_filter_parts.append(f"'{config.return_event}'")
    events_filter = ", ".join(events_filter_parts)

    query = f"""
        SELECT
            {interval_fn}(timestamp) AS time_window_start,
            event,
            [] AS breakdown_value,
            sumState(toUInt64(1)) AS count_state,
            uniqState(person_id) AS uniq_persons_state,
            uniqThetaState(person_id) AS uniq_theta_state
        FROM events
        WHERE event IN ({events_filter})
            AND timestamp >= {{time_window_min}}
            AND timestamp < {{time_window_max}}
        GROUP BY time_window_start, event
    """

    return query


def build_retention_combiner_query(
    config: RetentionPrecomputationConfig,
    date_from: datetime,
    date_to: datetime,
    total_intervals: int,
) -> str:
    """
    Build the combiner query for approximate retention using theta sketch intersections.

    This computes the retention matrix:
      For each cohort period (when users first did start_event),
      count how many also did return_event in each subsequent period.

    The query uses ClickHouse's bitmapAndCardinality to intersect theta sketches.

    Structure:
    1. Subquery 'cohort_sketches': merge theta sketches per period for start_event
    2. Subquery 'return_sketches': merge theta sketches per period for return_event
    3. Cross join + filter: for each (cohort_period, return_period) pair where
       return >= cohort, compute intersection cardinality

    Note: This is an APPROXIMATE approach. The intersection counts have ~2% error
    from the theta sketch approximation. Within-period ordering is not checked —
    if a user did the return event *before* the start event within the same period,
    they would still be counted. For daily periods, this is usually acceptable.
    """

    query = f"""
        WITH
            cohort_sketches AS (
                SELECT
                    time_window_start AS period,
                    uniqThetaMerge(uniq_theta_state) AS sketch
                FROM preaggregation_v2
                WHERE job_id IN {{job_ids}}
                    AND event = '{config.start_event}'
                    AND time_window_start >= {{time_start}}
                    AND time_window_start < {{time_end}}
                GROUP BY period
            ),
            return_sketches AS (
                SELECT
                    time_window_start AS period,
                    uniqThetaMerge(uniq_theta_state) AS sketch
                FROM preaggregation_v2
                WHERE job_id IN {{job_ids}}
                    AND event = '{config.return_event}'
                    AND time_window_start >= {{time_start}}
                    AND time_window_start < {{time_end}}
                GROUP BY period
            )
        SELECT
            c.period AS cohort_period,
            r.period AS return_period,
            bitmapAndCardinality(c.sketch, r.sketch) AS retained_users,
            bitmapCardinality(c.sketch) AS cohort_size,
            dateDiff('{config.interval}', c.period, r.period) AS intervals_from_base
        FROM cohort_sketches c
        CROSS JOIN return_sketches r
        WHERE r.period >= c.period
        ORDER BY cohort_period, return_period
    """

    return query


def build_retention_combiner_query_simple(
    config: RetentionPrecomputationConfig,
) -> str:
    """
    Simplified version that returns the standard retention matrix format:
      (cohort_index, interval_from_base, count)

    This can be directly consumed by the retention query runner's result formatter.
    """

    query = f"""
        WITH
            cohort_sketches AS (
                SELECT
                    time_window_start AS period,
                    uniqThetaMerge(uniq_theta_state) AS sketch
                FROM preaggregation_v2
                WHERE job_id IN {{job_ids}}
                    AND event = '{config.start_event}'
                    AND time_window_start >= {{time_start}}
                    AND time_window_start < {{time_end}}
                GROUP BY period
                ORDER BY period
            ),
            return_sketches AS (
                SELECT
                    time_window_start AS period,
                    uniqThetaMerge(uniq_theta_state) AS sketch
                FROM preaggregation_v2
                WHERE job_id IN {{job_ids}}
                    AND event = '{config.return_event}'
                    AND time_window_start >= {{time_start}}
                    AND time_window_start < {{time_end}}
                GROUP BY period
                ORDER BY period
            ),
            date_range AS (
                SELECT arrayJoin(
                    arrayMap(
                        i -> {{time_start}} + toIntervalDay(i),
                        range(0, dateDiff('day', {{time_start}}, {{time_end}}))
                    )
                ) AS period
            )
        SELECT
            indexOf(
                (SELECT groupArray(period) FROM date_range),
                c.period
            ) - 1 AS start_event_matching_interval,
            dateDiff('{config.interval}', c.period, r.period) AS intervals_from_base,
            bitmapAndCardinality(c.sketch, r.sketch) AS count
        FROM cohort_sketches c
        CROSS JOIN return_sketches r
        WHERE r.period >= c.period
        ORDER BY start_event_matching_interval, intervals_from_base
    """

    return query
