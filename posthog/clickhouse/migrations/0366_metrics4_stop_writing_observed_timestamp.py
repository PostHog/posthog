from django.conf import settings

from posthog.clickhouse.client.connection import NodeRole
from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions
from posthog.clickhouse.metrics import METRICS4_VIEW_SQL

DB = settings.CLICKHOUSE_LOGS_CLUSTER_DATABASE

# The view must stop the ARRAY JOIN of observed_timestamp_arr before the MV stops writing it.
# After that, new rows store an empty observed_timestamp_arr, so its length differs from the other point arrays.
# The column stays on metrics4_samples and writable_metrics4_samples until the ClickHouse team drops it.
operations = [
    run_sql_with_exceptions(METRICS4_VIEW_SQL(), node_roles=[NodeRole.LOGS]),
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
    groupArray(10000)(timestamp) AS timestamp_arr,
    groupArray(10000)(value) AS value_arr,
    groupArray(10000)(count) AS count_arr,
    groupArray(10000)(histogram_counts) AS histogram_counts_arr,
    groupArray(10000)(trace_id) AS trace_id_arr,
    groupArray(10000)(span_id) AS span_id_arr,
    groupArray(10000)(trace_flags) AS trace_flags_arr
FROM {DB}.metrics4_input
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
