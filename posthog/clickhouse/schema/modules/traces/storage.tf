# Tables that hold data, and the materialized views between them.

module "trace_attributes" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "trace_attributes")
  database     = var.database
  name         = "trace_attributes"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.trace_attributes${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toDate(original_expiry_time_bucket)"
  order_by     = "(team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value)"
  ttl          = var.ttl ? "original_expiry_time_bucket" : null
  columns      = local.trace_attributes_columns
  indexes = [
    { name = "idx_attribute_key", expression = "attribute_key", type = "bloom_filter(0.01)", granularity = 4 },
    { name = "idx_attribute_value", expression = "attribute_value", type = "bloom_filter(0.01)", granularity = 4 },
    { name = "idx_attribute_key_n3", expression = "attribute_key", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 4 },
    { name = "idx_attribute_value_n3", expression = "attribute_value", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 4 },
  ]
  override = try(var.overrides["trace_attributes"], {})
}

module "trace_attributes2" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "trace_attributes2")
  database     = var.database
  name         = "trace_attributes2"
  engine       = "ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.trace_attributes2${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toDate(original_expiry_time_bucket)"
  order_by     = "(team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value)"
  ttl          = var.ttl ? "original_expiry_time_bucket" : null
  columns      = local.trace_attributes_columns
  indexes = [
    { name = "idx_attribute_key", expression = "attribute_key", type = "bloom_filter(0.01)", granularity = 4 },
    { name = "idx_attribute_value", expression = "attribute_value", type = "bloom_filter(0.01)", granularity = 4 },
    { name = "idx_attribute_key_n3", expression = "attribute_key", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 4 },
    { name = "idx_attribute_value_n3", expression = "attribute_value", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 4 },
  ]
  override = try(var.overrides["trace_attributes2"], {})
}

module "trace_span_to_attributes" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "trace_span_to_attributes")
  database = var.database
  name     = "trace_span_to_attributes"
  to_table = "${var.database}.trace_attributes"
  query    = <<-SQL
    SELECT
        team_id,
        original_expiry_time_bucket,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        'span_attribute' AS attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            arrayJoin(mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes)) AS attribute,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.trace_spans
        GROUP BY
            team_id,
            original_expiry_time_bucket,
            time_bucket,
            service_name,
            resource_fingerprint,
            attribute
    )
  SQL
  override = try(var.overrides["trace_span_to_attributes"], {})

  depends_on = [
    module.trace_attributes,
    module.trace_spans,
  ]
}

module "trace_span_to_attributes2" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "trace_span_to_attributes2")
  database = var.database
  name     = "trace_span_to_attributes2"
  to_table = "${var.database}.trace_attributes2"
  query    = <<-SQL
    SELECT
        team_id,
        original_expiry_time_bucket,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        'span_attribute' AS attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            arrayJoin(mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes)) AS attribute,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.trace_spans
        GROUP BY
            team_id,
            original_expiry_time_bucket,
            time_bucket,
            service_name,
            resource_fingerprint,
            attribute
    )
  SQL
  override = try(var.overrides["trace_span_to_attributes2"], {})

  depends_on = [
    module.trace_attributes2,
    module.trace_spans,
  ]
}

module "trace_span_to_resource_attributes" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "trace_span_to_resource_attributes")
  database = var.database
  name     = "trace_span_to_resource_attributes"
  to_table = "${var.database}.trace_attributes"
  query    = <<-SQL
    SELECT
        team_id,
        original_expiry_time_bucket,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        'span_resource_attribute' AS attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            arrayJoin(resource_attributes) AS attribute,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.trace_spans
        GROUP BY
            team_id,
            original_expiry_time_bucket,
            time_bucket,
            service_name,
            resource_fingerprint,
            attribute
    )
  SQL
  override = try(var.overrides["trace_span_to_resource_attributes"], {})

  depends_on = [
    module.trace_attributes,
    module.trace_spans,
  ]
}

module "trace_span_to_resource_attributes2" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "trace_span_to_resource_attributes2")
  database = var.database
  name     = "trace_span_to_resource_attributes2"
  to_table = "${var.database}.trace_attributes2"
  query    = <<-SQL
    SELECT
        team_id,
        original_expiry_time_bucket,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        'span_resource_attribute' AS attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            arrayJoin(resource_attributes) AS attribute,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.trace_spans
        GROUP BY
            team_id,
            original_expiry_time_bucket,
            time_bucket,
            service_name,
            resource_fingerprint,
            attribute
    )
  SQL
  override = try(var.overrides["trace_span_to_resource_attributes2"], {})

  depends_on = [
    module.trace_attributes2,
    module.trace_spans,
  ]
}

module "trace_span_to_span_attributes" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "trace_span_to_span_attributes")
  database = var.database
  name     = "trace_span_to_span_attributes"
  to_table = "${var.database}.trace_attributes"
  query    = <<-SQL
    SELECT
        team_id,
        original_expiry_time_bucket,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        'span' AS attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            'name' AS attribute_key,
            name AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.trace_spans
        GROUP BY
            team_id,
            original_expiry_time_bucket,
            time_bucket,
            service_name,
            resource_fingerprint,
            name
    )
  SQL
  override = try(var.overrides["trace_span_to_span_attributes"], {})

  depends_on = [
    module.trace_attributes,
    module.trace_spans,
  ]
}

module "trace_span_to_span_attributes2" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "trace_span_to_span_attributes2")
  database = var.database
  name     = "trace_span_to_span_attributes2"
  to_table = "${var.database}.trace_attributes2"
  query    = <<-SQL
    SELECT
        team_id,
        original_expiry_time_bucket,
        time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        'span' AS attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            'name' AS attribute_key,
            name AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.trace_spans
        GROUP BY
            team_id,
            original_expiry_time_bucket,
            time_bucket,
            service_name,
            resource_fingerprint,
            name
    )
  SQL
  override = try(var.overrides["trace_span_to_span_attributes2"], {})

  depends_on = [
    module.trace_attributes2,
    module.trace_spans,
  ]
}

module "trace_spans" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "trace_spans")
  database     = var.database
  name         = "trace_spans"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.trace_spans${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toDate(original_expiry_timestamp)"
  order_by     = "(team_id, time_bucket, service_name, resource_fingerprint, status_code, name, timestamp)"
  ttl          = var.ttl ? "original_expiry_timestamp" : null
  settings     = "allow_part_offset_column_in_projections = 1, index_granularity = 8192, index_granularity_bytes = 104857600, map_serialization_version = 'with_buckets', ttl_only_drop_parts = 1"
  columns      = local.trace_spans_columns
  indexes = [
    { name = "idx_name", expression = "name", type = "ngrambf_v1(4, 5000, 2, 0)", granularity = 16 },
    { name = "idx_kind", expression = "kind", type = "minmax", granularity = 4 },
    { name = "idx_duration", expression = "duration_nano", type = "minmax", granularity = 1 },
    { name = "idx_status_code", expression = "status_code", type = "minmax", granularity = 1 },
    { name = "idx_timestamp_minmax", expression = "timestamp", type = "minmax", granularity = 1 },
    { name = "idx_observed_minmax", expression = "observed_timestamp", type = "minmax", granularity = 1 },
    { name = "idx_attributes_str_keys", expression = "mapKeys(attributes_map_str)", type = "bloom_filter(0.01)", granularity = 16 },
    { name = "idx_attributes_str_values", expression = "mapValues(attributes_map_str)", type = "bloom_filter(0.001)", granularity = 16 },
    { name = "idx_trace_bloom_part_v2", expression = "trace_id", type = "bloom_filter(0.05)", granularity = 99999 },
    { name = "idx_span_id_bloom_part_v2", expression = "span_id", type = "bloom_filter(0.05)", granularity = 99999 },
  ]
  projections = [
    { name = "projection_index_team_span_id", query = "SELECT team_id, _part_offset ORDER BY span_id" },
    { name = "projection_index_team_trace_id", query = "SELECT team_id, _part_offset ORDER BY trace_id" },
    { name = "projection_aggregate_counts", query = "SELECT team_id, time_bucket, toStartOfMinute(timestamp), service_name, resource_fingerprint, is_root_span, count() AS event_count GROUP BY team_id, time_bucket, toStartOfMinute(timestamp), service_name, resource_fingerprint, is_root_span" },
  ]
  override = try(var.overrides["trace_spans"], {})
}

module "trace_spans_kafka_metrics" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "trace_spans_kafka_metrics")
  database = var.database
  name     = "trace_spans_kafka_metrics"
  engine   = "ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.trace_spans_kafka_metrics${var.zk_path_suffix}', '{replica}-{shard}')"
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
  override = try(var.overrides["trace_spans_kafka_metrics"], {})
}

module "trace_spans_to_kafka_metrics_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "trace_spans_to_kafka_metrics_mv")
  database = var.database
  name     = "trace_spans_to_kafka_metrics_mv"
  to_table = "${var.database}.trace_spans_kafka_metrics"
  query    = <<-SQL
    SELECT
        _partition,
        _topic,
        maxSimpleState(_offset) AS max_offset,
        maxSimpleState(observed_timestamp) AS max_observed_timestamp,
        maxSimpleState(timestamp) AS max_timestamp,
        maxSimpleState(now()) AS max_created_at,
        maxSimpleState(now() - observed_timestamp) AS max_lag
    FROM ${var.database}.trace_spans
    GROUP BY
        _partition,
        _topic
  SQL
  override = try(var.overrides["trace_spans_to_kafka_metrics_mv"], {})

  depends_on = [
    module.trace_spans,
    module.trace_spans_kafka_metrics,
  ]
}
