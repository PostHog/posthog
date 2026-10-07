variable "node" {
  description = "The server these objects live on: { name, host, port, leader }. Null puts them on the provider's host."
  type        = any
  default     = null
}

variable "database" {
  description = "Database the objects live in."
  type        = string
  default     = "posthog"
}

variable "ttl" {
  description = "Set table TTLs. Tests turn them off, because they insert rows with old timestamps."
  type        = bool
  default     = true
}

variable "objects" {
  description = "Names of the objects to create."
  type        = set(string)
}

variable "test" {
  description = "Use the definitions the test suite expects."
  type        = bool
  default     = false
}

variable "deployment" { type = any }

locals {
  deployment = merge({ overrides = {} }, var.deployment)
}

locals {
}

# Column lists that more than one object uses.

locals {
  trace_attributes_columns = [
    { name = "team_id", type = "Int32" },
    { name = "original_expiry_time_bucket", type = "DateTime64(0)" },
    { name = "time_bucket", type = "DateTime64(0)" },
    { name = "service_name", type = "LowCardinality(String)" },
    { name = "resource_fingerprint", type = "UInt64", default_expression = "0" },
    { name = "attribute_key", type = "LowCardinality(String)" },
    { name = "attribute_value", type = "String" },
    { name = "attribute_type", type = "LowCardinality(String)" },
    { name = "attribute_count", type = "SimpleAggregateFunction(sum, UInt64)" },
  ]

  trace_spans_columns = [
    { name = "time_bucket", type = "DateTime", materialized_expression = "toStartOfInterval(timestamp, toIntervalHour(4))" },
    { name = "original_expiry_timestamp", type = "DateTime64(6)" },
    { name = "uuid", type = "String" },
    { name = "team_id", type = "Int32" },
    { name = "trace_id", type = "String" },
    { name = "span_id", type = "String" },
    { name = "parent_span_id", type = "String" },
    { name = "is_root_span", type = "Bool", materialized_expression = "replaceAll(trimRight(parent_span_id, '='), 'A', '') = ''" },
    { name = "trace_state", type = "String" },
    { name = "name", type = "LowCardinality(String)" },
    { name = "kind", type = "Int8" },
    { name = "flags", type = "UInt32" },
    { name = "timestamp", type = "DateTime64(6)" },
    { name = "end_time", type = "DateTime64(6)" },
    { name = "observed_timestamp", type = "DateTime64(6)" },
    { name = "created_at", type = "DateTime64(6)", materialized_expression = "now()" },
    { name = "duration_nano", type = "UInt64", materialized_expression = "toUInt64(dateDiff('microsecond', timestamp, end_time)) * 1000" },
    { name = "status_code", type = "Int16" },
    { name = "service_name", type = "LowCardinality(String)" },
    { name = "resource_attributes", type = "Map(LowCardinality(String), String)" },
    { name = "resource_fingerprint", type = "UInt64", materialized_expression = "cityHash64(resource_attributes)" },
    { name = "instrumentation_scope", type = "String" },
    { name = "attributes_map_str", type = "Map(LowCardinality(String), String)" },
    { name = "attributes", type = "Map(LowCardinality(String), String)", alias_expression = "mapApply((k, v) -> (left(k, -5), v), attributes_map_str)" },
    { name = "attributes_map_float", type = "Map(LowCardinality(String), Float64)", materialized_expression = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__float'), toFloat64OrNull(v)), attributes_map_str))" },
    { name = "attributes_map_datetime", type = "Map(LowCardinality(String), DateTime64(6))", materialized_expression = "mapFilter((k, v) -> (v IS NOT NULL), mapApply((k, v) -> (concat(left(k, -5), '__datetime'), parseDateTimeBestEffortOrNull(v, 6)), attributes_map_str))" },
    { name = "dropped_attributes_count", type = "UInt32" },
    { name = "dropped_events_count", type = "UInt32" },
    { name = "dropped_links_count", type = "UInt32" },
    { name = "events", type = "Array(String)" },
    { name = "links", type = "Array(String)" },
    { name = "_partition", type = "UInt32" },
    { name = "_topic", type = "String" },
    { name = "_offset", type = "UInt64" },
    { name = "_bytes_uncompressed", type = "UInt64" },
    { name = "_bytes_compressed", type = "UInt64" },
    { name = "_record_count", type = "UInt64" },
  ]
}

module "trace_attributes_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "trace_attributes_distributed"
  database = var.database
  layout   = "global"
  columns  = local.trace_attributes_columns
  storage = {
    partition_by = "toDate(original_expiry_time_bucket)"
    order_by     = "(team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value)"
    ttl          = var.ttl ? "original_expiry_time_bucket" : null
    indexes = [
      { name = "idx_attribute_key", expression = "attribute_key", type = "bloom_filter(0.01)", granularity = 4 },
      { name = "idx_attribute_value", expression = "attribute_value", type = "bloom_filter(0.01)", granularity = 4 },
      { name = "idx_attribute_key_n3", expression = "attribute_key", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 4 },
      { name = "idx_attribute_value_n3", expression = "attribute_value", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 4 },
    ]
  }
  routing = {
    read = true
  }
  deployment = merge({ read_cluster = "posthog_single_shard" }, local.deployment)
  names      = { storage = "trace_attributes" }
}

module "trace_attributes2_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "trace_attributes2"
  database = var.database
  layout   = "global"
  columns  = local.trace_attributes_columns
  storage = {
    engine       = "AggregatingMergeTree"
    partition_by = "toDate(original_expiry_time_bucket)"
    order_by     = "(team_id, attribute_type, time_bucket, resource_fingerprint, attribute_key, attribute_value)"
    ttl          = var.ttl ? "original_expiry_time_bucket" : null
    indexes = [
      { name = "idx_attribute_key", expression = "attribute_key", type = "bloom_filter(0.01)", granularity = 4 },
      { name = "idx_attribute_value", expression = "attribute_value", type = "bloom_filter(0.01)", granularity = 4 },
      { name = "idx_attribute_key_n3", expression = "attribute_key", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 4 },
      { name = "idx_attribute_value_n3", expression = "attribute_value", type = "ngrambf_v1(3, 32768, 3, 0)", granularity = 4 },
    ]
  }
  deployment = local.deployment
}

module "trace_spans_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "trace_spans_distributed"
  database = var.database
  layout   = "global"
  columns  = local.trace_spans_columns
  storage = {
    partition_by = "toDate(original_expiry_timestamp)"
    order_by     = "(team_id, time_bucket, service_name, resource_fingerprint, status_code, name, timestamp)"
    ttl          = var.ttl ? "original_expiry_timestamp" : null
    settings     = "allow_part_offset_column_in_projections = 1, index_granularity = 8192, index_granularity_bytes = 104857600, map_serialization_version = 'with_buckets', ttl_only_drop_parts = 1"
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
  }
  routing = {
    read         = true
    write        = false
    read_columns = local.trace_spans_columns
  }
  kafka = {
    topic          = "clickhouse_traces"
    consumer_group = "clickhouse-traces-avro"
    format         = "Avro"
    arguments      = "settings"
    columns = [
      { name = "uuid", type = "String" },
      { name = "trace_id", type = "String" },
      { name = "span_id", type = "String" },
      { name = "parent_span_id", type = "String" },
      { name = "trace_state", type = "String" },
      { name = "name", type = "String" },
      { name = "kind", type = "Int32" },
      { name = "flags", type = "Int32" },
      { name = "timestamp", type = "DateTime64(6)" },
      { name = "end_time", type = "DateTime64(6)" },
      { name = "observed_timestamp", type = "DateTime64(6)" },
      { name = "service_name", type = "String" },
      { name = "resource_attributes", type = "Map(LowCardinality(String), String)" },
      { name = "instrumentation_scope", type = "String" },
      { name = "attributes", type = "Map(LowCardinality(String), String)" },
      { name = "dropped_attributes_count", type = "Int32" },
      { name = "events", type = "Array(String)" },
      { name = "dropped_events_count", type = "Int32" },
      { name = "links", type = "Array(String)" },
      { name = "dropped_links_count", type = "Int32" },
      { name = "status_code", type = "Int32" },
      { name = "retention_days", type = "Nullable(Int32)" },
    ]
    settings = { input_format_avro_allow_missing_fields = "1", kafka_num_consumers = "1", kafka_poll_max_batch_size = "1000", kafka_poll_timeout_ms = "3000", kafka_skip_broken_messages = "100", kafka_thread_per_consumer = "1" }
  }
  mv_select = <<-SQL
uuid,
    trace_id,
    span_id,
    parent_span_id,
    trace_state,
    name,
    timestamp,
    end_time,
    observed_timestamp,
    service_name,
    instrumentation_scope,
    events,
    links,
    toInt8(kind) AS kind,
    toUInt32(flags) AS flags,
    toUInt32(dropped_attributes_count) AS dropped_attributes_count,
    toUInt32(dropped_events_count) AS dropped_events_count,
    toUInt32(dropped_links_count) AS dropped_links_count,
    toInt16(status_code) AS status_code,
    mapSort(mapApply((k, v) -> (concat(k, '__str'), JSONExtractString(v)), attributes)) AS attributes_map_str,
    mapSort(mapApply((k, v) -> (k, JSONExtractString(v)), resource_attributes)) AS resource_attributes,
    toInt32OrZero(_headers.value[indexOf(_headers.name, 'team_id')]) AS team_id,
    timestamp + toIntervalDay(if((retention_days IS NOT NULL) AND (retention_days > 0), retention_days, toInt32OrDefault(_headers.value[indexOf(_headers.name, 'retention-days')], toInt32(15)))) AS original_expiry_timestamp,
    _partition,
    _topic,
    _offset,
    toInt64OrDefault(_headers.value[indexOf(_headers.name, 'record_count')], toInt64(1)) AS _record_count,
    toInt64OrDefault(_headers.value[indexOf(_headers.name, 'bytes_uncompressed')], toInt64(0)) AS _bytes_uncompressed,
    toInt64OrDefault(_headers.value[indexOf(_headers.name, 'bytes_compressed')], toInt64(0)) AS _bytes_compressed
  SQL
  mv_target = "${var.database}.trace_spans"
  deployment = merge({
    read_cluster     = "posthog_single_shard"
    kafka_collection = "warpstream_traces"
  }, local.deployment)
  names = { storage = "trace_spans", mv = "kafka_trace_spans_avro_mv", kafka = "kafka_trace_spans_avro" }
}

module "trace_spans_kafka_metrics_family" {
  source  = "../../lib/table_family"
  node    = var.node
  objects = var.objects

  name     = "trace_spans_kafka_metrics"
  database = var.database
  layout   = "global"
  columns = [
    { name = "_partition", type = "UInt32" },
    { name = "_topic", type = "String" },
    { name = "max_offset", type = "SimpleAggregateFunction(max, UInt64)" },
    { name = "max_observed_timestamp", type = "SimpleAggregateFunction(max, DateTime64(9))" },
    { name = "max_timestamp", type = "SimpleAggregateFunction(max, DateTime64(9))" },
    { name = "max_created_at", type = "SimpleAggregateFunction(max, DateTime64(9))" },
    { name = "max_lag", type = "SimpleAggregateFunction(max, UInt64)" },
  ]
  storage = {
    order_by = "(_topic, _partition)"
  }
  deployment = local.deployment
}

# Tables that hold data, and the materialized views between them.



module "trace_span_to_attributes" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "trace_span_to_attributes")
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
  override = try(local.deployment.overrides["trace_span_to_attributes"], {})

  depends_on = [
    module.trace_attributes_family,
    module.trace_spans_family,
  ]
}

module "trace_span_to_attributes2" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "trace_span_to_attributes2")
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
  override = try(local.deployment.overrides["trace_span_to_attributes2"], {})

  depends_on = [
    module.trace_attributes2_family,
    module.trace_spans_family,
  ]
}

module "trace_span_to_resource_attributes" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "trace_span_to_resource_attributes")
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
  override = try(local.deployment.overrides["trace_span_to_resource_attributes"], {})

  depends_on = [
    module.trace_attributes_family,
    module.trace_spans_family,
  ]
}

module "trace_span_to_resource_attributes2" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "trace_span_to_resource_attributes2")
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
  override = try(local.deployment.overrides["trace_span_to_resource_attributes2"], {})

  depends_on = [
    module.trace_attributes2_family,
    module.trace_spans_family,
  ]
}

module "trace_span_to_span_attributes" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "trace_span_to_span_attributes")
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
  override = try(local.deployment.overrides["trace_span_to_span_attributes"], {})

  depends_on = [
    module.trace_attributes_family,
    module.trace_spans_family,
  ]
}

module "trace_span_to_span_attributes2" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "trace_span_to_span_attributes2")
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
  override = try(local.deployment.overrides["trace_span_to_span_attributes2"], {})

  depends_on = [
    module.trace_attributes2_family,
    module.trace_spans_family,
  ]
}



module "trace_spans_to_kafka_metrics_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "trace_spans_to_kafka_metrics_mv")
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
  override = try(local.deployment.overrides["trace_spans_to_kafka_metrics_mv"], {})

  depends_on = [
    module.trace_spans_family,
    module.trace_spans_kafka_metrics_family,
  ]
}
