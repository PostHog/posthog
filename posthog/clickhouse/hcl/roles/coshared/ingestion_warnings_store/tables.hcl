# The sharded_ingestion_warnings store, hosted by every cloud AUX node and the
# local data node. Base is the AUX form; the local node's partitioning, details
# codec and replication path are patches in roles/data/local.
database "posthog" {
  table "sharded_ingestion_warnings" {
    order_by     = ["team_id", "toHour(timestamp)", "type", "source", "timestamp"]
    partition_by = "toYear(timestamp)"
    settings = {
      index_granularity = "8192"
    }
    column "team_id" {
      type = "Int64"
    }
    column "source" {
      type = "LowCardinality(String)"
    }
    column "type" {
      type = "String"
    }
    column "details" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "_timestamp" {
      type = "DateTime"
    }
    column "_offset" {
      type = "UInt64"
    }
    column "_partition" {
      type = "UInt64"
    }
    engine "replicated_merge_tree" {
      zoo_path     = "/clickhouse/tables/reshard/{shard}/posthog.sharded_ingestion_warnings"
      replica_name = "{replica}"
    }
  }
}
