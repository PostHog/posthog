SELECT
    team_id,
    metric_name,
    time_bucket,
    series_fingerprint,
    resource_fingerprint,
    timestamp,
    observed_timestamp,
    original_expiry_timestamp,
    service_name,
    metric_type,
    value,
    count,
    histogram_bounds,
    histogram_counts,
    trace_id,
    span_id,
    trace_flags,
    has_labels,
    unit,
    aggregation_temporality,
    is_monotonic,
    instrumentation_scope
FROM posthog.metrics2
WHERE time_bucket > toDateTime('2026-08-25 00:00:00')
    AND time_bucket < toDateTime('2026-09-14 00:00:00')
    AND timestamp > toDateTime('2026-08-25 00:00:00')
    AND timestamp < toDateTime('2026-09-14 00:00:00')
UNION ALL
SELECT
    team_id,
    metric_name,
    time_bucket,
    series_fingerprint,
    resource_fingerprint,
    point_timestamp AS timestamp,
    point_observed_timestamp AS observed_timestamp,
    toDateTime64(original_expiry_date, 6) AS original_expiry_timestamp,
    service_name,
    metric_type,
    point_value AS value,
    point_count AS count,
    histogram_bounds,
    point_histogram_counts AS histogram_counts,
    point_trace_id AS trace_id,
    point_span_id AS span_id,
    point_trace_flags AS trace_flags,
    toBool(has_labels) AS has_labels,
    unit,
    aggregation_temporality,
    toBool(is_monotonic) AS is_monotonic,
    instrumentation_scope
FROM posthog.metrics4_samples
ARRAY JOIN
    timestamp_arr AS point_timestamp,
    observed_timestamp_arr AS point_observed_timestamp,
    value_arr AS point_value,
    count_arr AS point_count,
    histogram_counts_arr AS point_histogram_counts,
    trace_id_arr AS point_trace_id,
    span_id_arr AS point_span_id,
    trace_flags_arr AS point_trace_flags
WHERE time_bucket >= toDateTime('2026-09-14 00:00:00')
