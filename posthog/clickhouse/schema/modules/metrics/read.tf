# Distributed tables, views and dictionaries that queries read from.

module "metric_attributes_distributed" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "metric_attributes_distributed")
  database = var.database
  name     = "metric_attributes_distributed"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'metric_attributes2')"
  columns  = local.metric_attributes2_columns
  override = try(var.overrides["metric_attributes_distributed"], {})
}

module "metric_samples" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "metric_samples")
  database = var.database
  name     = "metric_samples"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'metric_samples1')"
  columns  = local.metric_samples1_columns
  override = try(var.overrides["metric_samples"], {})
}

module "metric_series" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "metric_series")
  database = var.database
  name     = "metric_series"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'metric_series1')"
  columns  = local.metric_series1_columns
  override = try(var.overrides["metric_series"], {})
}

module "metric_series_distributed" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "metric_series_distributed")
  database = var.database
  name     = "metric_series_distributed"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'metric_series2')"
  columns  = local.metric_series2_columns
  override = try(var.overrides["metric_series_distributed"], {})
}

module "metrics" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "metrics")
  database = var.database
  name     = "metrics"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'metrics1')"
  columns  = local.metrics1_columns
  override = try(var.overrides["metrics"], {})
}

module "metrics4_view" {
  source = "../../lib/view"

  enabled  = local.read && !contains(var.exclude, "metrics4_view")
  database = var.database
  name     = "metrics4_view"
  query    = <<-SQL
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
    FROM ${var.database}.metrics2
    WHERE (time_bucket > toDateTime('2026-08-25 00:00:00')) AND (time_bucket < toDateTime('2026-09-14 00:00:00')) AND (timestamp > toDateTime('2026-08-25 00:00:00')) AND (timestamp < toDateTime('2026-09-14 00:00:00'))
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
    FROM ${var.database}.metrics4_samples
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
  SQL
  override = try(var.overrides["metrics4_view"], {})

  depends_on = [
    module.metrics2,
    module.metrics4_samples,
  ]
}

module "metrics_distributed" {
  source = "../../lib/table"

  enabled  = local.read && !contains(var.exclude, "metrics_distributed")
  database = var.database
  name     = "metrics_distributed"
  engine   = "Distributed('posthog_single_shard', '${var.database}', 'metrics2')"
  columns  = local.metrics2_columns
  override = try(var.overrides["metrics_distributed"], {})
}
