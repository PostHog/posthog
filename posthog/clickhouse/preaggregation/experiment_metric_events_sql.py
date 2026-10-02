# Table for storing preaggregated experiment metric events
#
# Instead of scanning the events table on every experiment query to find
# metric events (funnel steps, mean values, etc.), we compute this once
# and store it here. Subsequent queries read from this table instead of
# scanning events.
#
# For funnels: one row per event per entity per job.
# For mean/ratio: one row per entity per job.
# Deduplicated by ReplacingMergeTree on the full ORDER BY key.
#
# Supported metric types:
# - Funnel: uses `steps` array for step indicators
# - Mean: uses `numeric_value` for the computed metric value
# - Ratio: two separate jobs (numerator + denominator), both use `numeric_value`
# - Retention: uses `steps` with exactly two flags — steps[1] = matched the
#   start_event predicate, steps[2] = matched the completion_event predicate
#   (an event can match both). Start anchoring, the per-user retention window,
#   and the maturity gate are all computed at read time from `timestamp`.


TABLE_BASE_NAME = "experiment_metric_events_preaggregated"


def DISTRIBUTED_EXPERIMENT_METRIC_EVENTS_TABLE():
    return TABLE_BASE_NAME


def SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE():
    return f"sharded_{TABLE_BASE_NAME}"


def TRUNCATE_EXPERIMENT_METRIC_EVENTS_TABLE_SQL():
    return f"TRUNCATE TABLE IF EXISTS {SHARDED_EXPERIMENT_METRIC_EVENTS_TABLE()}"
