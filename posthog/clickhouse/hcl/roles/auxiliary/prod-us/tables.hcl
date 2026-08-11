database "posthog" {
  table "ingestion_warnings_main" {
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
      type  = "String"
      codec = "ZSTD(3)"
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
    engine "distributed" {
      cluster_name    = "posthog"
      remote_database = "posthog"
      remote_table    = "sharded_ingestion_warnings"
      sharding_key    = "rand()"
    }
  }
}
