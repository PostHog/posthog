"""
Trends precomputation using the generalized preaggregation_v2 table.

Builds INSERT queries that precompute hourly aggregate states per (event, breakdown),
and combiner queries that merge those states back for the requested interval.

Supported math types:
- total (count): sumState(1) → sumMerge(count_state)
- dau (unique users): uniqState(person_id) → uniqMerge(uniq_persons_state)
- unique_session: uniqState($session_id) → uniqMerge(uniq_sessions_state)
- sum/min/max(property): {func}State(toFloat64(property)) → {func}Merge({func}_state)
- avg(property): sumState + count → sumMerge / sumMerge(count_state)

Unsupported (need full event scan):
- weekly_active, monthly_active (can be built from daily uniq states — future work)
- median, p75, p90, p95, p99 (quantileState is mergeable but not currently in the table)
- first_time_for_user (requires global knowledge)
- count_per_actor variants (require per-actor grouping)
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class TrendsPrecomputationConfig:
    """Configuration for a trends precomputation job."""

    event: str
    math_type: str  # "total", "dau", "unique_session", "sum", "min", "max", "avg"
    math_property: str | None = None  # property name for property math
    breakdown_expr: str | None = None  # HogQL expression for breakdown dimension


# Maps math types to the columns they populate and their write/read-side functions
MATH_TYPE_MAPPING: dict[str, dict[str, str]] = {
    "total": {
        "write_select": "sumState(toUInt64(1)) AS count_state",
        "read_merge": "sumMerge(count_state)",
    },
    "dau": {
        "write_select": "uniqState(person_id) AS uniq_persons_state",
        "read_merge": "uniqMerge(uniq_persons_state)",
    },
    "unique_session": {
        "write_select": "uniqState(events.`$session_id`) AS uniq_sessions_state",
        "read_merge": "uniqMerge(uniq_sessions_state)",
    },
    "sum": {
        "write_select": "sumState(toFloat64(events.properties.{property})) AS sum_state",
        "read_merge": "sumMerge(sum_state)",
    },
    "min": {
        "write_select": "minState(toFloat64(events.properties.{property})) AS min_state",
        "read_merge": "minMerge(min_state)",
    },
    "max": {
        "write_select": "maxState(toFloat64(events.properties.{property})) AS max_state",
        "read_merge": "maxMerge(max_state)",
    },
    "avg": {
        # avg = sum / count, both are stored
        "write_select": (
            "sumState(toFloat64(events.properties.{property})) AS sum_state, sumState(toUInt64(1)) AS count_state"
        ),
        "read_merge": "sumMerge(sum_state) / sumMerge(count_state)",
    },
}

SUPPORTED_MATH_TYPES = frozenset(MATH_TYPE_MAPPING.keys())

# Interval name → ClickHouse function for rollup from hourly buckets
INTERVAL_ROLLUP_FUNCTIONS: dict[str, str] = {
    "hour": "toStartOfHour(time_window_start)",
    "day": "toStartOfDay(time_window_start)",
    "week": "toStartOfWeek(time_window_start, 0)",
    "month": "toStartOfMonth(time_window_start)",
}


def build_trends_insert_query(config: TrendsPrecomputationConfig) -> str:
    """
    Build the INSERT SELECT query for trends precomputation.

    The query aggregates events into hourly buckets with the appropriate
    aggregate state functions. Uses {time_window_min} and {time_window_max}
    placeholders for the executor to substitute per-job.

    Returns a query string suitable for ensure_precomputed().
    """
    if config.math_type not in SUPPORTED_MATH_TYPES:
        raise ValueError(f"Unsupported math type: {config.math_type}. Supported: {SUPPORTED_MATH_TYPES}")

    mapping = MATH_TYPE_MAPPING[config.math_type]
    write_select = mapping["write_select"]

    if config.math_property and "{property}" in write_select:
        write_select = write_select.replace("{property}", config.math_property)

    # Build breakdown expression
    if config.breakdown_expr:
        breakdown_select = f"[toString({config.breakdown_expr})] AS breakdown_value"
        breakdown_group = ", breakdown_value"
    else:
        breakdown_select = "[] AS breakdown_value"
        breakdown_group = ""

    query = f"""
        SELECT
            toStartOfHour(timestamp) AS time_window_start,
            '{config.event}' AS event,
            {breakdown_select},
            {write_select}
        FROM events
        WHERE event = '{config.event}'
            AND timestamp >= {{time_window_min}}
            AND timestamp < {{time_window_max}}
        GROUP BY time_window_start, event{breakdown_group}
    """

    return query


def build_trends_combiner_query(
    config: TrendsPrecomputationConfig,
    interval: str,
    time_start: datetime,
    time_end: datetime,
) -> tuple[str, dict]:
    """
    Build the combiner query that reads from precomputed data.

    Returns the HogQL query string and a dict of placeholder names
    that need to be filled (job_ids, time_start, time_end).

    The query merges hourly precomputed states into the requested interval.
    """
    if config.math_type not in SUPPORTED_MATH_TYPES:
        raise ValueError(f"Unsupported math type: {config.math_type}")

    if interval not in INTERVAL_ROLLUP_FUNCTIONS:
        raise ValueError(f"Unsupported interval: {interval}. Supported: {list(INTERVAL_ROLLUP_FUNCTIONS.keys())}")

    mapping = MATH_TYPE_MAPPING[config.math_type]
    read_merge = mapping["read_merge"]

    if config.math_property and "{property}" in read_merge:
        read_merge = read_merge.replace("{property}", config.math_property)

    rollup_fn = INTERVAL_ROLLUP_FUNCTIONS[interval]

    # Build breakdown handling in the combiner
    if config.breakdown_expr:
        breakdown_select = ", arrayElement(breakdown_value, 1) AS breakdown"
        breakdown_group = ", breakdown"
    else:
        breakdown_select = ""
        breakdown_group = ""

    query = f"""
        SELECT
            {rollup_fn} AS interval_start,
            {read_merge} AS value
            {breakdown_select}
        FROM preaggregation_v2
        WHERE job_id IN {{job_ids}}
            AND event = '{config.event}'
            AND time_window_start >= {{time_start}}
            AND time_window_start < {{time_end}}
        GROUP BY interval_start{breakdown_group}
        ORDER BY interval_start
    """

    return query, {
        "job_ids": "placeholder",
        "time_start": time_start,
        "time_end": time_end,
    }


def can_precompute_trends_series(math_type: str | None) -> bool:
    """Check if a trends series math type can be precomputed."""
    if math_type is None:
        math_type = "total"
    return math_type in SUPPORTED_MATH_TYPES
