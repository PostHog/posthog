# prod-eu deltas to coshared base objects.
database "posthog" {
  patch_table "sharded_events_recent" {
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/batch_exports/{shard}/posthog.sharded_events_recent"
      replica_name   = "{replica}"
      version_column = "_timestamp"
    }
  }

  patch_table "sharded_events_json_recent" {
    settings = {
      parts_to_delay_insert = "800"
      parts_to_throw_insert = "1500"
    }
    engine "replicated_replacing_merge_tree" {
      zoo_path       = "/clickhouse/tables/batch_exports/{shard}/posthog.sharded_events_json_recent"
      replica_name   = "{replica}"
      version_column = "_timestamp"
    }
  }
}
