from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

HISTOGRAM_BOUNDS_ARR = "histogram_bounds_arr SimpleAggregateFunction(groupArrayArray(10000), Array(Array(Float64)))"

# Expand step: add the column, then write it. The series-hour histogram_bounds column stays until readers move.
# The storage table gets the column before the writable table, and both before the MV writes it.
# Rows written before the MV change store an empty array. When a merge combines them with newer rows of the same
# series-hour, histogram_bounds_arr is shorter than timestamp_arr, so readers fall back to histogram_bounds there.
operations = [
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.metrics4_samples ADD COLUMN IF NOT EXISTS {HISTOGRAM_BOUNDS_ARR}",
        node_roles=[NodeRole.LOGS],
        sharded=False,
        is_alter_on_replicated_table=True,
    ),
    run_sql_with_exceptions(
        f"ALTER TABLE {DB}.writable_metrics4_samples ADD COLUMN IF NOT EXISTS {HISTOGRAM_BOUNDS_ARR}",
        node_roles=[NodeRole.APM],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
    run_sql_with_exceptions(
        f"""ALTER TABLE {DB}.metrics4_input_to_metrics4_samples MODIFY QUERY
SELECT
    team_id,
    metric_name,
    toDateTime(toStartOfHour(timestamp)) AS time_bucket,
    series_fingerprint,
    toDate32(original_expiry_timestamp) AS original_expiry_date,
    any(resource_fingerprint) AS resource_fingerprint,
    any(service_name) AS service_name,
    any(metric_type) AS metric_type,
    any(unit) AS unit,
    any(aggregation_temporality) AS aggregation_temporality,
    max(toUInt8(is_monotonic)) AS is_monotonic,
    max(toUInt8(has_labels)) AS has_labels,
    any(instrumentation_scope) AS instrumentation_scope,
    anyLast(histogram_bounds) AS histogram_bounds,
    any(_topic) AS _topic,
    groupArray(10000)(input.timestamp) AS timestamp_arr,
    groupArray(10000)(input.value) AS value_arr,
    groupArray(10000)(input.count) AS count_arr,
    groupArray(10000)(input.histogram_counts) AS histogram_counts_arr,
    groupArray(10000)(input.trace_id) AS trace_id_arr,
    groupArray(10000)(input.span_id) AS span_id_arr,
    groupArray(10000)(input.trace_flags) AS trace_flags_arr,
    groupArray(10000)(input.histogram_bounds) AS histogram_bounds_arr
FROM {DB}.metrics4_input AS input
GROUP BY
    team_id,
    metric_name,
    time_bucket,
    series_fingerprint,
    original_expiry_date""",
        node_roles=[NodeRole.APM],
        sharded=False,
        is_alter_on_replicated_table=False,
    ),
]
