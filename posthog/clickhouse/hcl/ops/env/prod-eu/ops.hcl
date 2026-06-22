# OPS prod-eu env layer — sharded_tophog (tophog zoo_path)
#
# query_log_archive_old (legacy/transitional) is intentionally unmanaged — not
# authored here and trimmed from the golden, so it is left untouched on the cluster.
#
# Generated/maintained as the declarative source of truth for the OPS ClickHouse cluster.
# Resolve with: hclexp load -layer <base>,<...>

database "posthog" {
  table "sharded_tophog" {
    order_by     = ["pipeline", "lane", "metric", "timestamp", "key"]
    partition_by = "toYYYYMMDD(timestamp)"
    ttl          = "toDate(timestamp) + toIntervalDay(30)"
    settings = {
      index_granularity   = "8192"
      ttl_only_drop_parts = "1"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "metric" {
      type = "LowCardinality(String)"
    }
    column "type" {
      type = "LowCardinality(String)"
    }
    column "key" {
      type = "Map(LowCardinality(String), String)"
    }
    column "value" {
      type = "Float64"
    }
    column "count" {
      type = "UInt64"
    }
    column "pipeline" {
      type = "LowCardinality(String)"
    }
    column "lane" {
      type = "LowCardinality(String)"
    }
    column "labels" {
      type = "Map(LowCardinality(String), String)"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/ops/{shard}/posthog.tophog"
      replica_name = "{replica}"
    }
  }
}
