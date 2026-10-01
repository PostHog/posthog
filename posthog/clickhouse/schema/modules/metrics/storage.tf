# Tables that hold data, and the materialized views between them.

module "metric_attributes" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "metric_attributes")
  database     = var.database
  name         = "metric_attributes"
  engine       = "ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.metric_attributes${var.zk_path_suffix}', '{replica}')"
  partition_by = "toDate(time_bucket)"
  order_by     = "(team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value)"
  settings     = "deduplicate_merge_projection_mode = 'drop', index_granularity = 8192"
  columns = [
    { name = "team_id", type = "Int32" },
    { name = "time_bucket", type = "DateTime64(0)" },
    { name = "service_name", type = "LowCardinality(String)" },
    { name = "resource_fingerprint", type = "UInt64", default_expression = "0" },
    { name = "attribute_key", type = "LowCardinality(String)" },
    { name = "attribute_value", type = "String" },
    { name = "attribute_count", type = "SimpleAggregateFunction(sum, UInt64)" },
    { name = "attribute_type", type = "LowCardinality(String)" },
  ]
  indexes = [
    { name = "idx_attribute_key", expression = "attribute_key", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attribute_value", expression = "attribute_value", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attribute_key_n3", expression = "attribute_key", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
    { name = "idx_attribute_value_n3", expression = "attribute_value", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
  ]
  override = try(var.overrides["metric_attributes"], {})
}

module "metric_attributes2" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "metric_attributes2")
  database     = var.database
  name         = "metric_attributes2"
  engine       = "ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.metric_attributes2${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toDate(original_expiry_time_bucket)"
  order_by     = "(team_id, attribute_type, time_bucket, attribute_key, attribute_value)"
  ttl          = var.ttl ? "original_expiry_time_bucket" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.metric_attributes2_columns
  indexes = [
    { name = "idx_attribute_key", expression = "attribute_key", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attribute_value", expression = "attribute_value", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attribute_key_n3", expression = "attribute_key", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
    { name = "idx_attribute_value_n3", expression = "attribute_value", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
  ]
  override = try(var.overrides["metric_attributes2"], {})
}

module "metric_attributes3" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "metric_attributes3")
  database     = var.database
  name         = "metric_attributes3"
  engine       = "ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.metric_attributes3${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toDate(original_expiry_time_bucket)"
  order_by     = "(team_id, metric_name, attribute_type, time_bucket, attribute_key, attribute_value, service_name, original_expiry_time_bucket)"
  ttl          = var.ttl ? "original_expiry_time_bucket" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.metric_attributes3_columns
  indexes = [
    { name = "idx_attribute_key", expression = "attribute_key", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attribute_value", expression = "attribute_value", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attribute_key_n3", expression = "attribute_key", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
    { name = "idx_attribute_value_n3", expression = "attribute_value", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
  ]
  override = try(var.overrides["metric_attributes3"], {})
}

module "metric_names3" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "metric_names3")
  database     = var.database
  name         = "metric_names3"
  engine       = "ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.metric_names3${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toDate(original_expiry_time_bucket)"
  order_by     = "(team_id, time_bucket, metric_name, original_expiry_time_bucket)"
  ttl          = var.ttl ? "original_expiry_timestamp" : null
  columns      = local.metric_names3_columns
  override     = try(var.overrides["metric_names3"], {})
}

module "metric_samples1" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "metric_samples1")
  database     = var.database
  name         = "metric_samples1"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.metric_samples1${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toDate(timestamp)"
  order_by     = "(team_id, metric_name, series_fingerprint, timestamp)"
  ttl          = var.ttl ? "toDateTime(timestamp) + toIntervalDay(30)" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.metric_samples1_columns
  indexes = [
    { name = "idx_trace_id_bf", expression = "trace_id", type = "bloom_filter(0.01)", granularity = 1 },
  ]
  override = try(var.overrides["metric_samples1"], {})
}

module "metric_series1" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "metric_series1")
  database = var.database
  name     = "metric_series1"
  engine   = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.metric_series1${var.zk_path_suffix}', '{replica}-{shard}', last_seen)"
  order_by = "(team_id, metric_name, series_fingerprint)"
  ttl      = var.ttl ? "toDateTime(last_seen) + toIntervalDay(90)" : null
  columns  = local.metric_series1_columns
  indexes = [
    { name = "idx_service_set", expression = "service_name", type = "set(1000)", granularity = 1 },
    { name = "idx_attr_keys", expression = "mapKeys(attributes)", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attr_values", expression = "mapValues(attributes)", type = "bloom_filter(0.01)", granularity = 1 },
  ]
  override = try(var.overrides["metric_series1"], {})
}

module "metric_series2" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "metric_series2")
  database = var.database
  name     = "metric_series2"
  engine   = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.metric_series2${var.zk_path_suffix}', '{replica}-{shard}', last_seen)"
  order_by = "(team_id, metric_name, series_fingerprint)"
  ttl      = var.ttl ? "original_expiry_timestamp" : null
  columns  = local.metric_series2_columns
  indexes = [
    { name = "idx_service_set", expression = "service_name", type = "set(1000)", granularity = 1 },
    { name = "idx_resource_fingerprint", expression = "resource_fingerprint", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attr_keys", expression = "mapKeys(attributes)", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attr_values", expression = "mapValues(attributes)", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_last_seen_minmax", expression = "last_seen", type = "minmax", granularity = 1 },
  ]
  override = try(var.overrides["metric_series2"], {})
}

module "metric_series3" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "metric_series3")
  database     = var.database
  name         = "metric_series3"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.metric_series3${var.zk_path_suffix}', '{replica}-{shard}', last_seen)"
  partition_by = "toDate(original_expiry_timestamp)"
  order_by     = "(team_id, metric_name, series_fingerprint)"
  ttl          = var.ttl ? "original_expiry_timestamp" : null
  columns      = local.metric_series2_columns
  indexes = [
    { name = "idx_service_set", expression = "service_name", type = "set(1000)", granularity = 1 },
    { name = "idx_resource_fingerprint", expression = "resource_fingerprint", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attr_keys", expression = "mapKeys(attributes)", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attr_values", expression = "mapValues(attributes)", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_last_seen_minmax", expression = "last_seen", type = "minmax", granularity = 1 },
  ]
  override = try(var.overrides["metric_series3"], {})
}

module "metrics1" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "metrics1")
  database     = var.database
  name         = "metrics1"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.metrics1${var.zk_path_suffix}', '{replica}')"
  partition_by = "toDate(timestamp)"
  order_by     = "(team_id, time_bucket, service_name, metric_name, resource_fingerprint, timestamp)"
  settings     = "index_granularity = 8192, index_granularity_bytes = 104857600, ttl_only_drop_parts = 1"
  columns      = local.metrics1_columns
  indexes = [
    { name = "idx_metric_name_set", expression = "metric_name", type = "set(100)", granularity = 1 },
    { name = "idx_metric_type_set", expression = "metric_type", type = "set(10)", granularity = 1 },
    { name = "idx_attributes_str_keys", expression = "mapKeys(attributes_map_str)", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attributes_str_values", expression = "mapValues(attributes_map_str)", type = "bloom_filter(0.001)", granularity = 1 },
    { name = "idx_observed_minmax", expression = "observed_timestamp", type = "minmax", granularity = 1 },
  ]
  projections = [
    { name = "projection_aggregate_counts", query = "SELECT team_id, time_bucket, toStartOfMinute(timestamp), service_name, metric_name, metric_type, resource_fingerprint, count() AS event_count, sum(value) AS total_value, min(value) AS min_value, max(value) AS max_value GROUP BY team_id, time_bucket, toStartOfMinute(timestamp), service_name, metric_name, metric_type, resource_fingerprint" },
  ]
  override = try(var.overrides["metrics1"], {})
}

module "metrics2" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "metrics2")
  database     = var.database
  name         = "metrics2"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.metrics2${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toDate(original_expiry_timestamp)"
  order_by     = "(team_id, metric_name, time_bucket, series_fingerprint, timestamp)"
  ttl          = var.ttl ? "original_expiry_timestamp" : null
  settings     = "index_granularity = 8192, index_granularity_bytes = 104857600, ttl_only_drop_parts = 1"
  columns      = local.metrics2_columns
  indexes = [
    { name = "idx_metric_type_set", expression = "metric_type", type = "set(10)", granularity = 1 },
    { name = "idx_service_set", expression = "service_name", type = "set(1000)", granularity = 1 },
    { name = "idx_trace_id_bf", expression = "trace_id", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_resource_fingerprint", expression = "resource_fingerprint", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_observed_minmax", expression = "observed_timestamp", type = "minmax", granularity = 1 },
    { name = "idx_timestamp_minmax", expression = "timestamp", type = "minmax", granularity = 1 },
  ]
  projections = [
    { name = "projection_series_activity", query = "SELECT team_id, service_name, metric_name, metric_type, resource_fingerprint, series_fingerprint, toStartOfHour(timestamp) AS hour, count() AS sample_count, max(timestamp) AS last_seen GROUP BY team_id, service_name, metric_name, metric_type, resource_fingerprint, series_fingerprint, hour" },
  ]
  override = try(var.overrides["metrics2"], {})
}

module "metrics2_input" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "metrics2_input")
  database = var.database
  name     = "metrics2_input"
  engine   = "`Null`"
  columns  = local.metrics2_input_columns
  override = try(var.overrides["metrics2_input"], {})
}

module "metrics2_input_to_metric_attributes" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "metrics2_input_to_metric_attributes")
  database = var.database
  name     = "metrics2_input_to_metric_attributes"
  to_table = "${var.database}.metric_attributes2"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        attribute_key,
        attribute_value,
        attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(timestamp, toIntervalHour(1)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalHour(1)) AS original_expiry_time_bucket,
            service_name AS service_name,
            mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS filtered_attributes,
            arrayJoin(filtered_attributes) AS attribute,
            'metric' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.metrics2_input
        WHERE has_labels
        GROUP BY
            team_id,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            filtered_attributes
    )
  SQL
  override = try(var.overrides["metrics2_input_to_metric_attributes"], {})

  depends_on = [
    module.metric_attributes2,
    module.metrics2_input,
  ]
}

module "metrics2_input_to_metric_attributes3" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "metrics2_input_to_metric_attributes3")
  database = var.database
  name     = "metrics2_input_to_metric_attributes3"
  to_table = "${var.database}.metric_attributes3"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        attribute_key,
        attribute_value,
        attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            metric_name AS metric_name,
            toStartOfInterval(timestamp, toIntervalHour(1)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalHour(1)) AS original_expiry_time_bucket,
            service_name AS service_name,
            mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS filtered_attributes,
            arrayJoin(filtered_attributes) AS attribute,
            'metric' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.metrics2_input
        WHERE has_labels
        GROUP BY
            team_id,
            metric_name,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            filtered_attributes
    )
  SQL
  override = try(var.overrides["metrics2_input_to_metric_attributes3"], {})

  depends_on = [
    module.metric_attributes3,
    module.metrics2_input,
  ]
}

module "metrics2_input_to_metric_names3" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "metrics2_input_to_metric_names3")
  database = var.database
  name     = "metrics2_input_to_metric_names3"
  to_table = "${var.database}.metric_names3"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        toStartOfHour(timestamp) AS time_bucket,
        toStartOfHour(input.original_expiry_timestamp) AS original_expiry_time_bucket,
        maxSimpleState(input.original_expiry_timestamp) AS original_expiry_timestamp
    FROM ${var.database}.metrics2_input AS input
    WHERE has_labels
    GROUP BY
        team_id,
        time_bucket,
        metric_name,
        original_expiry_time_bucket
  SQL
  override = try(var.overrides["metrics2_input_to_metric_names3"], {})

  depends_on = [
    module.metric_names3,
    module.metrics2_input,
  ]
}

module "metrics2_input_to_metric_series" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "metrics2_input_to_metric_series")
  database = var.database
  name     = "metrics2_input_to_metric_series"
  to_table = "${var.database}.metric_series2"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        series_fingerprint,
        metric_type,
        unit,
        aggregation_temporality,
        is_monotonic,
        service_name,
        instrumentation_scope,
        resource_attributes,
        attributes,
        timestamp AS last_seen,
        original_expiry_timestamp
    FROM ${var.database}.metrics2_input
    WHERE has_labels
  SQL
  override = try(var.overrides["metrics2_input_to_metric_series"], {})

  depends_on = [
    module.metric_series2,
    module.metrics2_input,
  ]
}

module "metrics2_input_to_metric_series3" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "metrics2_input_to_metric_series3")
  database = var.database
  name     = "metrics2_input_to_metric_series3"
  to_table = "${var.database}.metric_series3"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        series_fingerprint,
        metric_type,
        unit,
        aggregation_temporality,
        is_monotonic,
        service_name,
        instrumentation_scope,
        resource_attributes,
        attributes,
        timestamp AS last_seen,
        original_expiry_timestamp
    FROM ${var.database}.metrics2_input
    WHERE has_labels
  SQL
  override = try(var.overrides["metrics2_input_to_metric_series3"], {})

  depends_on = [
    module.metric_series3,
    module.metrics2_input,
  ]
}

module "metrics2_input_to_metrics" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "metrics2_input_to_metrics")
  database = var.database
  name     = "metrics2_input_to_metrics"
  to_table = "${var.database}.metrics2"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
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
        instrumentation_scope,
        _partition,
        _topic,
        _offset
    FROM ${var.database}.metrics2_input
  SQL
  override = try(var.overrides["metrics2_input_to_metrics"], {})

  depends_on = [
    module.metrics2,
    module.metrics2_input,
  ]
}

module "metrics2_input_to_resource_attributes" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "metrics2_input_to_resource_attributes")
  database = var.database
  name     = "metrics2_input_to_resource_attributes"
  to_table = "${var.database}.metric_attributes2"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        attribute_key,
        attribute_value,
        attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(timestamp, toIntervalHour(1)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalHour(1)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_attributes AS filtered_attributes,
            arrayJoin(filtered_attributes) AS attribute,
            'resource' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.metrics2_input
        WHERE has_labels
        GROUP BY
            team_id,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            filtered_attributes
    )
  SQL
  override = try(var.overrides["metrics2_input_to_resource_attributes"], {})

  depends_on = [
    module.metric_attributes2,
    module.metrics2_input,
  ]
}

module "metrics2_input_to_resource_attributes3" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "metrics2_input_to_resource_attributes3")
  database = var.database
  name     = "metrics2_input_to_resource_attributes3"
  to_table = "${var.database}.metric_attributes3"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        attribute_key,
        attribute_value,
        attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            metric_name AS metric_name,
            toStartOfInterval(timestamp, toIntervalHour(1)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalHour(1)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_attributes AS filtered_attributes,
            arrayJoin(filtered_attributes) AS attribute,
            'resource' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.metrics2_input
        WHERE has_labels
        GROUP BY
            team_id,
            metric_name,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            filtered_attributes
    )
  SQL
  override = try(var.overrides["metrics2_input_to_resource_attributes3"], {})

  depends_on = [
    module.metric_attributes3,
    module.metrics2_input,
  ]
}

module "metrics4_attributes" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "metrics4_attributes")
  database     = var.database
  name         = "metrics4_attributes"
  engine       = "ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.metrics4_attributes${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toDate(original_expiry_time_bucket)"
  order_by     = "(team_id, metric_name, attribute_type, time_bucket, attribute_key, attribute_value, service_name, original_expiry_time_bucket)"
  ttl          = var.ttl ? "original_expiry_time_bucket" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.metric_attributes3_columns
  indexes = [
    { name = "idx_attribute_key", expression = "attribute_key", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attribute_value", expression = "attribute_value", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attribute_key_n3", expression = "attribute_key", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
    { name = "idx_attribute_value_n3", expression = "attribute_value", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
  ]
  override = try(var.overrides["metrics4_attributes"], {})
}

module "metrics4_input" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "metrics4_input")
  database = var.database
  name     = "metrics4_input"
  engine   = "`Null`"
  columns  = local.metrics2_input_columns
  override = try(var.overrides["metrics4_input"], {})
}

module "metrics4_input_to_metrics4_attributes" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "metrics4_input_to_metrics4_attributes")
  database = var.database
  name     = "metrics4_input_to_metrics4_attributes"
  to_table = "${var.database}.writable_metrics4_attributes"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        attribute_key,
        attribute_value,
        attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            metric_name AS metric_name,
            toStartOfInterval(timestamp, toIntervalHour(1)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalHour(1)) AS original_expiry_time_bucket,
            service_name AS service_name,
            mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS filtered_attributes,
            arrayJoin(filtered_attributes) AS attribute,
            'metric' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.metrics4_input
        WHERE has_labels
        GROUP BY
            team_id,
            metric_name,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            filtered_attributes
    )
  SQL
  override = try(var.overrides["metrics4_input_to_metrics4_attributes"], {})

  depends_on = [
    module.metrics4_input,
    module.writable_metrics4_attributes,
  ]
}

module "metrics4_input_to_metrics4_names" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "metrics4_input_to_metrics4_names")
  database = var.database
  name     = "metrics4_input_to_metrics4_names"
  to_table = "${var.database}.writable_metrics4_names"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        toStartOfHour(timestamp) AS time_bucket,
        toStartOfHour(input.original_expiry_timestamp) AS original_expiry_time_bucket,
        maxSimpleState(input.original_expiry_timestamp) AS original_expiry_timestamp
    FROM ${var.database}.metrics4_input AS input
    WHERE has_labels
    GROUP BY
        team_id,
        time_bucket,
        metric_name,
        original_expiry_time_bucket
  SQL
  override = try(var.overrides["metrics4_input_to_metrics4_names"], {})

  depends_on = [
    module.metrics4_input,
    module.writable_metrics4_names,
  ]
}

module "metrics4_input_to_metrics4_resource_attributes" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "metrics4_input_to_metrics4_resource_attributes")
  database = var.database
  name     = "metrics4_input_to_metrics4_resource_attributes"
  to_table = "${var.database}.writable_metrics4_attributes"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        attribute_key,
        attribute_value,
        attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            metric_name AS metric_name,
            toStartOfInterval(timestamp, toIntervalHour(1)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalHour(1)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_attributes AS filtered_attributes,
            arrayJoin(filtered_attributes) AS attribute,
            'resource' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.metrics4_input
        WHERE has_labels
        GROUP BY
            team_id,
            metric_name,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            filtered_attributes
    )
  SQL
  override = try(var.overrides["metrics4_input_to_metrics4_resource_attributes"], {})

  depends_on = [
    module.metrics4_input,
    module.writable_metrics4_attributes,
  ]
}

module "metrics4_input_to_metrics4_samples" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "metrics4_input_to_metrics4_samples")
  database = var.database
  name     = "metrics4_input_to_metrics4_samples"
  to_table = "${var.database}.writable_metrics4_samples"
  query    = <<-SQL
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
        groupArray(10000)(observed_timestamp) AS observed_timestamp_arr,
        groupArray(10000)(value) AS value_arr,
        groupArray(10000)(count) AS count_arr,
        groupArray(10000)(histogram_counts) AS histogram_counts_arr,
        groupArray(10000)(trace_id) AS trace_id_arr,
        groupArray(10000)(span_id) AS span_id_arr,
        groupArray(10000)(trace_flags) AS trace_flags_arr
    FROM ${var.database}.metrics4_input
    GROUP BY
        team_id,
        metric_name,
        time_bucket,
        series_fingerprint,
        original_expiry_date
  SQL
  override = try(var.overrides["metrics4_input_to_metrics4_samples"], {})

  depends_on = [
    module.metrics4_input,
    module.writable_metrics4_samples,
  ]
}

module "metrics4_input_to_metrics4_series" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "metrics4_input_to_metrics4_series")
  database = var.database
  name     = "metrics4_input_to_metrics4_series"
  to_table = "${var.database}.writable_metrics4_series"
  query    = <<-SQL
    SELECT
        team_id,
        metric_name,
        series_fingerprint,
        metric_type,
        unit,
        aggregation_temporality,
        is_monotonic,
        service_name,
        instrumentation_scope,
        resource_attributes,
        attributes,
        timestamp,
        original_expiry_timestamp
    FROM ${var.database}.metrics4_input
    WHERE has_labels
  SQL
  override = try(var.overrides["metrics4_input_to_metrics4_series"], {})

  depends_on = [
    module.metrics4_input,
    module.writable_metrics4_series,
  ]
}

module "metrics4_names" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "metrics4_names")
  database     = var.database
  name         = "metrics4_names"
  engine       = "ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.metrics4_names${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toDate(original_expiry_time_bucket)"
  order_by     = "(team_id, time_bucket, metric_name, original_expiry_time_bucket)"
  ttl          = var.ttl ? "original_expiry_timestamp" : null
  columns      = local.metric_names3_columns
  override     = try(var.overrides["metrics4_names"], {})
}

module "metrics4_samples" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "metrics4_samples")
  database     = var.database
  name         = "metrics4_samples"
  engine       = "ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.metrics4_samples${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "original_expiry_date"
  order_by     = "(team_id, metric_name, time_bucket, series_fingerprint)"
  ttl          = var.ttl ? "original_expiry_date" : null
  settings     = "index_granularity = 128, ttl_only_drop_parts = 1"
  columns = [
    { name = "team_id", type = "Int32" },
    { name = "metric_name", type = "LowCardinality(String)" },
    { name = "time_bucket", type = "DateTime" },
    { name = "series_fingerprint", type = "UInt64", codec = "Delta(8), Default" },
    { name = "original_expiry_date", type = "Date32" },
    { name = "resource_fingerprint", type = "SimpleAggregateFunction(any, UInt64)" },
    { name = "service_name", type = "SimpleAggregateFunction(any, LowCardinality(String))" },
    { name = "metric_type", type = "SimpleAggregateFunction(any, LowCardinality(String))" },
    { name = "unit", type = "SimpleAggregateFunction(any, LowCardinality(String))" },
    { name = "aggregation_temporality", type = "SimpleAggregateFunction(any, LowCardinality(String))" },
    { name = "is_monotonic", type = "SimpleAggregateFunction(max, UInt8)" },
    { name = "has_labels", type = "SimpleAggregateFunction(max, UInt8)" },
    { name = "instrumentation_scope", type = "SimpleAggregateFunction(any, String)" },
    { name = "histogram_bounds", type = "SimpleAggregateFunction(anyLast, Array(Float64))" },
    { name = "_topic", type = "SimpleAggregateFunction(any, LowCardinality(String))" },
    { name = "timestamp_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(DateTime64(6)))", codec = "DoubleDelta, Default" },
    { name = "observed_timestamp_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(DateTime64(6)))", codec = "DoubleDelta, Default" },
    { name = "value_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(Float64))", codec = "Gorilla(8), Default" },
    { name = "count_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(UInt64))", codec = "T64, Default" },
    { name = "histogram_counts_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(Array(UInt64)))", codec = "T64, Default" },
    { name = "trace_id_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(String))" },
    { name = "span_id_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(String))" },
    { name = "trace_flags_arr", type = "SimpleAggregateFunction(groupArrayArray(10000), Array(Int32))" },
    { name = "timestamp_min", type = "DateTime64(6)", alias_expression = "arrayMin(timestamp_arr)" },
    { name = "timestamp_max", type = "DateTime64(6)", alias_expression = "arrayMax(timestamp_arr)" },
  ]
  indexes = [
    { name = "idx_metric_type_set", expression = "metric_type", type = "set(10)", granularity = 1 },
    { name = "idx_time_bucket_minmax", expression = "time_bucket", type = "minmax", granularity = 1 },
    { name = "idx_trace_id_bf", expression = "trace_id_arr", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_timestamp_min_minmax", expression = "timestamp_min", type = "minmax", granularity = 1 },
    { name = "idx_timestamp_max_minmax", expression = "timestamp_max", type = "minmax", granularity = 1 },
  ]
  override = try(var.overrides["metrics4_samples"], {})
}

module "metrics4_series" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "metrics4_series")
  database     = var.database
  name         = "metrics4_series"
  engine       = "ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.metrics4_series${var.zk_path_suffix}', '{replica}-{shard}', timestamp)"
  partition_by = "toStartOfWeek(original_expiry_timestamp)"
  order_by     = "(team_id, metric_name, series_fingerprint, time_bucket)"
  ttl          = var.ttl ? "original_expiry_timestamp" : null
  settings     = "index_granularity = 1024, ttl_only_drop_parts = 1"
  columns = [
    { name = "team_id", type = "Int32" },
    { name = "metric_name", type = "LowCardinality(String)" },
    { name = "series_fingerprint", type = "UInt64", codec = "Delta(8), Default" },
    { name = "metric_type", type = "LowCardinality(String)" },
    { name = "unit", type = "LowCardinality(String)" },
    { name = "aggregation_temporality", type = "LowCardinality(String)" },
    { name = "is_monotonic", type = "Bool", default_expression = "false" },
    { name = "service_name", type = "LowCardinality(String)" },
    { name = "instrumentation_scope", type = "String" },
    { name = "resource_attributes", type = "Map(LowCardinality(String), String)" },
    { name = "resource_fingerprint", type = "UInt64", materialized_expression = "cityHash64(resource_attributes)" },
    { name = "attributes", type = "Map(LowCardinality(String), String)" },
    { name = "timestamp", type = "DateTime64(6)" },
    { name = "time_bucket", type = "DateTime", materialized_expression = "toStartOfHour(timestamp)" },
    { name = "original_expiry_timestamp", type = "DateTime64(6)" },
  ]
  indexes = [
    { name = "idx_service_set", expression = "service_name", type = "set(1000)", granularity = 1 },
    { name = "idx_resource_fingerprint", expression = "resource_fingerprint", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attr_keys", expression = "mapKeys(attributes)", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attr_values", expression = "mapValues(attributes)", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_timestamp_minmax", expression = "timestamp", type = "minmax", granularity = 1 },
    { name = "idx_time_bucket_minmax", expression = "time_bucket", type = "minmax", granularity = 1 },
  ]
  override = try(var.overrides["metrics4_series"], {})
}

module "metrics_kafka_metrics" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "metrics_kafka_metrics")
  database = var.database
  name     = "metrics_kafka_metrics"
  engine   = "ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.metrics_kafka_metrics${var.zk_path_suffix}', '{replica}')"
  order_by = "(_topic, _partition)"
  columns = [
    { name = "_partition", type = "UInt32" },
    { name = "_topic", type = "String" },
    { name = "max_offset", type = "SimpleAggregateFunction(max, UInt64)" },
    { name = "max_observed_timestamp", type = "SimpleAggregateFunction(max, DateTime64(9))" },
    { name = "max_timestamp", type = "SimpleAggregateFunction(max, DateTime64(9))" },
    { name = "max_created_at", type = "SimpleAggregateFunction(max, DateTime64(9))" },
    { name = "max_lag", type = "SimpleAggregateFunction(max, UInt64)" },
  ]
  override = try(var.overrides["metrics_kafka_metrics"], {})
}
