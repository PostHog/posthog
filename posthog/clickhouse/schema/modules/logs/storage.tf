# Tables that hold data, and the materialized views between them.

module "kafka_logs_avro_billing_metrics_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "kafka_logs_avro_billing_metrics_mv")
  database = var.database
  name     = "kafka_logs_avro_billing_metrics_mv"
  to_table = "${var.database}.logs_billing_metrics"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        service_name,
        sumSimpleState(_bytes_uncompressed) AS bytes_uncompressed,
        sumSimpleState(_bytes_compressed) AS bytes_compressed,
        sumSimpleState(1) AS record_count
    FROM
    (
        SELECT
            team_id,
            toStartOfInterval(timestamp, toIntervalMinute(1)) AS time_bucket,
            service_name AS service_name,
            _bytes_uncompressed,
            _bytes_compressed
        FROM ${var.database}.logs34
    )
    GROUP BY
        team_id,
        time_bucket,
        service_name
  SQL
  override = try(var.overrides["kafka_logs_avro_billing_metrics_mv"], {})

  depends_on = [
    module.logs34,
    module.logs_billing_metrics,
  ]
}

module "kafka_logs_avro_kafka_metrics_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "kafka_logs_avro_kafka_metrics_mv")
  database = var.database
  name     = "kafka_logs_avro_kafka_metrics_mv"
  to_table = "${var.database}.logs_kafka_metrics"
  query    = <<-SQL
    SELECT
        _partition,
        _topic,
        maxSimpleState(_offset) AS max_offset,
        maxSimpleState(observed_timestamp) AS max_observed_timestamp,
        maxSimpleState(timestamp) AS max_timestamp,
        maxSimpleState(now()) AS max_created_at,
        maxSimpleState(now() - observed_timestamp) AS max_lag
    FROM ${var.database}.logs34
    GROUP BY
        _partition,
        _topic
  SQL
  override = try(var.overrides["kafka_logs_avro_kafka_metrics_mv"], {})

  depends_on = [
    module.logs34,
    module.logs_kafka_metrics,
  ]
}

module "log_attributes" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "log_attributes")
  database     = var.database
  name         = "log_attributes"
  engine       = "ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.log_attributes${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toDate(original_expiry_time_bucket)"
  order_by     = "(team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value)"
  settings     = "deduplicate_merge_projection_mode = 'drop', index_granularity = 8192, storage_policy = 'default'"
  columns = [
    { name = "team_id", type = "Int32", codec = "DoubleDelta, ZSTD(1)" },
    { name = "time_bucket", type = "DateTime64(0)", codec = "DoubleDelta, ZSTD(1)" },
    { name = "original_expiry_time_bucket", type = "DateTime64(0)", codec = "DoubleDelta, ZSTD(1)" },
    { name = "service_name", type = "LowCardinality(String)", codec = "ZSTD(1)" },
    { name = "resource_fingerprint", type = "UInt64", default_expression = "0", codec = "DoubleDelta, ZSTD(1)" },
    { name = "attribute_key", type = "LowCardinality(String)", codec = "ZSTD(1)" },
    { name = "attribute_value", type = "String", codec = "ZSTD(1)" },
    { name = "attribute_count", type = "SimpleAggregateFunction(sum, UInt64)" },
    { name = "attribute_type", type = "LowCardinality(String)" },
  ]
  indexes = [
    { name = "idx_attribute_key", expression = "attribute_key", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attribute_value", expression = "attribute_value", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attribute_key_n3", expression = "attribute_key", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
    { name = "idx_attribute_value_n3", expression = "attribute_value", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
  ]
  override = try(var.overrides["log_attributes"], {})
}

module "log_attributes2" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "log_attributes2")
  database     = var.database
  name         = "log_attributes2"
  engine       = "ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.log_attributes2${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toDate(original_expiry_time_bucket)"
  order_by     = "(team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value)"
  ttl          = var.ttl ? "original_expiry_time_bucket" : null
  settings     = "deduplicate_merge_projection_mode = 'drop', index_granularity = 8192"
  columns      = local.log_attributes2_columns
  indexes = [
    { name = "idx_attribute_key", expression = "attribute_key", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attribute_value", expression = "attribute_value", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attribute_key_n3", expression = "attribute_key", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
    { name = "idx_attribute_value_n3", expression = "attribute_value", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
  ]
  override = try(var.overrides["log_attributes2"], {})
}

module "log_attributes3" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "log_attributes3")
  database     = var.database
  name         = "log_attributes3"
  engine       = "ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.log_attributes3${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toDate(original_expiry_time_bucket)"
  order_by     = "(team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value, severity_text)"
  ttl          = var.ttl ? "original_expiry_time_bucket" : null
  settings     = "deduplicate_merge_projection_mode = 'drop', index_granularity = 8192"
  columns      = local.log_attributes3_columns
  indexes = [
    { name = "idx_attribute_key", expression = "attribute_key", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attribute_value", expression = "attribute_value", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attribute_key_n3", expression = "attribute_key", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
    { name = "idx_attribute_value_n3", expression = "attribute_value", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 1 },
  ]
  override = try(var.overrides["log_attributes3"], {})
}

module "logs32" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "logs32")
  database     = var.database
  name         = "logs32"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.logs32${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toDate(original_expiry_timestamp)"
  order_by     = "(team_id, time_bucket, service_name, resource_fingerprint, severity_text, timestamp)"
  settings     = "add_minmax_index_for_numeric_columns = 1, allow_experimental_reverse_key = 1, allow_remote_fs_zero_copy_replication = 1, index_granularity = 8192, index_granularity_bytes = 104857600, storage_policy = 'default', ttl_only_drop_parts = 1"
  columns      = local.logs32_columns
  indexes = [
    { name = "idx_severity_text_set", expression = "severity_text", type = "set(10)", granularity = 1 },
    { name = "idx_attributes_str_keys", expression = "mapKeys(attributes_map_str)", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attributes_str_values", expression = "mapValues(attributes_map_str)", type = "bloom_filter(0.001)", granularity = 1 },
    { name = "idx_mat_body_ipv4_matches", expression = "mat_body_ipv4_matches", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_body_ngram3", expression = "lower(body)", type = "ngrambf_v1(3, 25000, 2, 0)", granularity = 1 },
    { name = "idx_uuid_bloom", expression = "uuid", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_observed_minmax", expression = "observed_timestamp", type = "minmax", granularity = 1 },
    { name = "idx_timestamp_minmax", expression = "timestamp", type = "minmax", granularity = 1 },
  ]
  projections = [
    { name = "projection_aggregate_counts", query = "SELECT team_id, time_bucket, toStartOfMinute(timestamp), service_name, severity_text, resource_fingerprint, count() AS event_count GROUP BY team_id, time_bucket, toStartOfMinute(timestamp), service_name, severity_text, resource_fingerprint" },
  ]
  override = try(var.overrides["logs32"], {})
}

module "logs32_to_log_attributes" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "logs32_to_log_attributes")
  database = var.database
  name     = "logs32_to_log_attributes"
  to_table = "${var.database}.log_attributes"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS attributes,
            arrayJoin(attributes) AS attribute,
            'log' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.logs32
        GROUP BY
            team_id,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            resource_fingerprint,
            attributes
    )
  SQL
  override = try(var.overrides["logs32_to_log_attributes"], {})

  depends_on = [
    module.log_attributes,
    module.logs32,
  ]
}

module "logs32_to_resource_attributes" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "logs32_to_resource_attributes")
  database = var.database
  name     = "logs32_to_resource_attributes"
  to_table = "${var.database}.log_attributes"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        attribute_type,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            arrayJoin(resource_attributes) AS attribute,
            'resource' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.logs32
        GROUP BY
            team_id,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            resource_fingerprint,
            resource_attributes
    )
  SQL
  override = try(var.overrides["logs32_to_resource_attributes"], {})

  depends_on = [
    module.log_attributes,
    module.logs32,
  ]
}

module "logs34" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "logs34")
  database     = var.database
  name         = "logs34"
  engine       = "ReplicatedMergeTree('/clickhouse/tables/noshard/posthog.logs34${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toDate(original_expiry_timestamp)"
  order_by     = "(team_id, time_bucket, service_name, resource_fingerprint, severity_text, timestamp)"
  ttl          = var.ttl ? "original_expiry_timestamp" : null
  settings     = "add_minmax_index_for_numeric_columns = 1, allow_experimental_reverse_key = 1, index_granularity = 8192, index_granularity_bytes = 104857600, map_serialization_version = 'with_buckets', ttl_only_drop_parts = 1"
  columns      = local.logs34_columns
  indexes = [
    { name = "idx_severity_text_set", expression = "severity_text", type = "set(10)", granularity = 1 },
    { name = "idx_attributes_str_keys", expression = "mapKeys(attributes_map_str)", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_attributes_str_values", expression = "mapValues(attributes_map_str)", type = "bloom_filter(0.001)", granularity = 1 },
    { name = "idx_mat_body_ipv4_matches", expression = "mat_body_ipv4_matches", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_body_ngram3", expression = "lower(body)", type = "ngrambf_v1(3, 25000, 2, 0)", granularity = 1 },
    { name = "idx_uuid_bloom", expression = "uuid", type = "bloom_filter(0.01)", granularity = 1 },
    { name = "idx_observed_minmax", expression = "observed_timestamp", type = "minmax", granularity = 1 },
    { name = "idx_timestamp_minmax", expression = "timestamp", type = "minmax", granularity = 1 },
  ]
  projections = [
    { name = "projection_aggregate_counts", query = "SELECT team_id, time_bucket, toStartOfMinute(timestamp), service_name, severity_text, resource_fingerprint, count() AS event_count GROUP BY team_id, time_bucket, toStartOfMinute(timestamp), service_name, severity_text, resource_fingerprint" },
  ]
  override = try(var.overrides["logs34"], {})
}

module "logs34_to_log_attributes3" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "logs34_to_log_attributes3")
  database = var.database
  name     = "logs34_to_log_attributes3"
  to_table = "${var.database}.log_attributes3"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        attribute_type,
        severity_text,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            severity_text AS severity_text,
            mapFilter((k, v) -> ((length(k) < 256) AND (length(v) < 256)), attributes) AS attributes,
            arrayJoin(attributes) AS attribute,
            'log' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.logs34
        GROUP BY
            team_id,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            resource_fingerprint,
            severity_text,
            attributes
    )
  SQL
  override = try(var.overrides["logs34_to_log_attributes3"], {})

  depends_on = [
    module.log_attributes3,
    module.logs34,
  ]
}

module "logs34_to_resource_attributes3" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "logs34_to_resource_attributes3")
  database = var.database
  name     = "logs34_to_resource_attributes3"
  to_table = "${var.database}.log_attributes3"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        original_expiry_time_bucket,
        service_name,
        resource_fingerprint,
        attribute_key,
        attribute_value,
        attribute_type,
        severity_text,
        attribute_count
    FROM
    (
        SELECT
            team_id AS team_id,
            toStartOfInterval(timestamp, toIntervalMinute(10)) AS time_bucket,
            toStartOfInterval(original_expiry_timestamp, toIntervalMinute(10)) AS original_expiry_time_bucket,
            service_name AS service_name,
            resource_fingerprint,
            severity_text AS severity_text,
            arrayJoin(resource_attributes) AS attribute,
            'resource' AS attribute_type,
            attribute.1 AS attribute_key,
            attribute.2 AS attribute_value,
            sumSimpleState(1) AS attribute_count
        FROM ${var.database}.logs34
        GROUP BY
            team_id,
            time_bucket,
            original_expiry_time_bucket,
            service_name,
            resource_fingerprint,
            severity_text,
            resource_attributes
    )
  SQL
  override = try(var.overrides["logs34_to_resource_attributes3"], {})

  depends_on = [
    module.log_attributes3,
    module.logs34,
  ]
}

module "logs34_to_volume_buckets" {
  source = "../../lib/materialized_view"

  enabled  = local.storage && !contains(var.exclude, "logs34_to_volume_buckets")
  database = var.database
  name     = "logs34_to_volume_buckets"
  to_table = "${var.database}.logs_volume_buckets"
  query    = <<-SQL
    SELECT
        team_id,
        time_bucket,
        service_name,
        namespace,
        environment,
        severity_text,
        maxSimpleState(retention_days) AS retention_days,
        sumSimpleState(1) AS log_count
    FROM
    (
        SELECT
            team_id,
            toStartOfInterval(timestamp, toIntervalSecond(300), 'UTC') AS time_bucket,
            service_name,
            if((resource_attributes['k8s.namespace.name']) != '', resource_attributes['k8s.namespace.name'], resource_attributes['service.namespace']) AS namespace,
            if((resource_attributes['deployment.environment.name']) != '', resource_attributes['deployment.environment.name'], if((resource_attributes['deployment.environment']) != '', resource_attributes['deployment.environment'], resource_attributes['env'])) AS environment,
            lower(severity_text) AS severity_text,
            toUInt16(least(intDiv(greatest(dateDiff('microsecond', time_bucket, original_expiry_timestamp), 0) + 86399999999, 86400000000), 3650)) AS retention_days
        FROM ${var.database}.logs34
    )
    GROUP BY
        team_id,
        time_bucket,
        service_name,
        namespace,
        environment,
        severity_text
  SQL
  override = try(var.overrides["logs34_to_volume_buckets"], {})

  depends_on = [
    module.logs34,
    module.logs_volume_buckets,
  ]
}

module "logs_billing_metrics" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "logs_billing_metrics")
  database     = var.database
  name         = "logs_billing_metrics"
  engine       = "ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.logs_billing_metrics${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toYYYYMM(time_bucket)"
  order_by     = "(team_id, time_bucket, service_name)"
  settings     = "deduplicate_merge_projection_mode = 'rebuild', index_granularity = 8192"
  columns      = local.logs_billing_metrics_columns
  override     = try(var.overrides["logs_billing_metrics"], {})
}

module "logs_kafka_metrics" {
  source = "../../lib/table"

  enabled  = local.storage && !contains(var.exclude, "logs_kafka_metrics")
  database = var.database
  name     = "logs_kafka_metrics"
  engine   = "ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.logs_kafka_metrics${var.zk_path_suffix}', '{replica}-{shard}')"
  order_by = "(_topic, _partition)"
  columns  = local.logs_kafka_metrics_columns
  override = try(var.overrides["logs_kafka_metrics"], {})
}

module "logs_pattern_buckets" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "logs_pattern_buckets")
  database     = var.database
  name         = "logs_pattern_buckets"
  engine       = "ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.logs_pattern_buckets${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toDate(time_bucket)"
  primary_key  = "(team_id, time_bucket, service_name, namespace, environment, severity_text, pattern_version)"
  order_by     = "(team_id, time_bucket, service_name, namespace, environment, severity_text, pattern_version, pattern)"
  ttl          = var.ttl ? "time_bucket + toIntervalDay(42)" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 1"
  columns      = local.logs_pattern_buckets_columns
  override     = try(var.overrides["logs_pattern_buckets"], {})
}

module "logs_volume_buckets" {
  source = "../../lib/table"

  enabled      = local.storage && !contains(var.exclude, "logs_volume_buckets")
  database     = var.database
  name         = "logs_volume_buckets"
  engine       = "ReplicatedAggregatingMergeTree('/clickhouse/tables/noshard/posthog.logs_volume_buckets${var.zk_path_suffix}', '{replica}-{shard}')"
  partition_by = "toDate(time_bucket)"
  order_by     = "(team_id, time_bucket, service_name, namespace, environment, severity_text)"
  ttl          = var.ttl ? "time_bucket + toIntervalDay(greatest(42, retention_days))" : null
  settings     = "index_granularity = 8192, ttl_only_drop_parts = 0"
  columns      = local.logs_volume_buckets_columns
  override     = try(var.overrides["logs_volume_buckets"], {})
}
