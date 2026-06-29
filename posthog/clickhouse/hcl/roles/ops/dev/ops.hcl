# OPS dev env layer — prom_metrics experiment (dev only)
#
# Generated/maintained as the declarative source of truth for the OPS ClickHouse cluster.
# Resolve with: hclexp load -layer <base>,<...>
database "posthog" {
  table "prom_metrics" {
    column "id" {
      type    = "UUID"
      default = "reinterpretAsUUID(sipHash128(metric_name, all_tags))"
    }
    column "timestamp" {
      type = "DateTime64(3)"
    }
    column "value" {
      type = "Float64"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "tags" {
      type = "Map(LowCardinality(String), String)"
    }
    column "all_tags" {
      type = "Map(String, String)"
    }
    column "min_time" {
      type = "Nullable(DateTime64(3))"
    }
    column "max_time" {
      type = "Nullable(DateTime64(3))"
    }
    column "metric_family_name" {
      type = "String"
    }
    column "type" {
      type = "String"
    }
    column "unit" {
      type = "String"
    }
    column "help" {
      type = "String"
    }
    engine "time_series" {
      samples {
        target = "posthog.prom_metrics_data"
      }
      tags {
        target = "posthog.prom_metrics_tags"
      }
      metrics {
        target = "posthog.prom_metrics_metrics"
      }
    }
  }
  table "prom_metrics_data" {
    order_by = ["id", "timestamp"]
    settings = {
      index_granularity = "8192"
    }
    column "id" {
      type = "UUID"
    }
    column "timestamp" {
      type = "DateTime64(3)"
    }
    column "value" {
      type = "Float64"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/ops/tables/{shard}/posthog.prom_metrics/data"
      replica_name = "{replica}"
    }
  }
  table "prom_metrics_metrics" {
    order_by = ["metric_family_name"]
    settings = {
      index_granularity = "8192"
    }
    column "metric_family_name" {
      type = "String"
    }
    column "type" {
      type = "String"
    }
    column "unit" {
      type = "String"
    }
    column "help" {
      type = "String"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path     = "/clickhouse/ops/tables/{shard}/posthog.prom_metrics/metrics"
      replica_name = "{replica}"
    }
  }
  table "prom_metrics_tags" {
    primary_key = ["metric_name"]
    order_by    = ["metric_name", "id"]
    settings = {
      index_granularity = "8192"
    }
    column "id" {
      type    = "UUID"
      default = "reinterpretAsUUID(sipHash128(metric_name, all_tags))"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "tags" {
      type = "Map(LowCardinality(String), String)"
    }
    column "all_tags" {
      type = "Map(String, String)"
    }
    column "min_time" {
      type = "SimpleAggregateFunction(min, Nullable(DateTime64(3)))"
    }
    column "max_time" {
      type = "SimpleAggregateFunction(max, Nullable(DateTime64(3)))"
    }
    engine "replicated_aggregating_merge_tree" {
      zoo_path     = "/clickhouse/ops/tables/{shard}/posthog.prom_metrics/tags"
      replica_name = "{replica}"
    }
  }
  table "writable_prom_metrics" {
    column "id" {
      type    = "UUID"
      default = "reinterpretAsUUID(sipHash128(metric_name, all_tags))"
    }
    column "timestamp" {
      type = "DateTime64(3)"
    }
    column "value" {
      type = "Float64"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "tags" {
      type = "Map(LowCardinality(String), String)"
    }
    column "all_tags" {
      type = "Map(String, String)"
    }
    column "min_time" {
      type = "Nullable(DateTime64(3))"
    }
    column "max_time" {
      type = "Nullable(DateTime64(3))"
    }
    column "metric_family_name" {
      type = "String"
    }
    column "type" {
      type = "String"
    }
    column "unit" {
      type = "String"
    }
    column "help" {
      type = "String"
    }
    engine "time_series" {
      samples {
        target = "posthog.writable_prom_metrics_data"
      }
      tags {
        target = "posthog.writable_prom_metrics_tags"
      }
      metrics {
        target = "posthog.writable_prom_metrics_metrics"
      }
    }
  }
  table "writable_prom_metrics_data" {
    column "id" {
      type = "UUID"
    }
    column "timestamp" {
      type = "DateTime64(3)"
    }
    column "value" {
      type = "Float64"
    }
    engine "buffer" {
      database   = "posthog"
      table      = "prom_metrics_data"
      num_layers = 1
      min_time   = 2
      max_time   = 5
      min_rows   = 1
      max_rows   = 1000000
      min_bytes  = 1
      max_bytes  = 100000000
    }
  }
  table "writable_prom_metrics_metrics" {
    column "metric_family_name" {
      type = "String"
    }
    column "type" {
      type = "String"
    }
    column "unit" {
      type = "String"
    }
    column "help" {
      type = "String"
    }
    engine "buffer" {
      database   = "posthog"
      table      = "prom_metrics_metrics"
      num_layers = 1
      min_time   = 2
      max_time   = 5
      min_rows   = 1
      max_rows   = 1000000
      min_bytes  = 1
      max_bytes  = 100000000
    }
  }
  table "writable_prom_metrics_tags" {
    column "id" {
      type    = "UUID"
      default = "reinterpretAsUUID(sipHash128(metric_name, all_tags))"
    }
    column "metric_name" {
      type = "LowCardinality(String)"
    }
    column "tags" {
      type = "Map(LowCardinality(String), String)"
    }
    column "all_tags" {
      type = "Map(String, String)"
    }
    column "min_time" {
      type = "SimpleAggregateFunction(min, Nullable(DateTime64(3)))"
    }
    column "max_time" {
      type = "SimpleAggregateFunction(max, Nullable(DateTime64(3)))"
    }
    engine "buffer" {
      database   = "posthog"
      table      = "prom_metrics_tags"
      num_layers = 1
      min_time   = 2
      max_time   = 5
      min_rows   = 1
      max_rows   = 1000000
      min_bytes  = 1
      max_bytes  = 100000000
    }
  }
}
