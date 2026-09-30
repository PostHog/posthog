database "posthog" {
  table "channel_definition" {
    override = true
    column "domain" {
      type = "String"
    }
    column "kind" {
      type = "String"
    }
    column "domain_type" {
      type = "Nullable(String)"
    }
    column "type_if_paid" {
      type = "Nullable(String)"
    }
    column "type_if_organic" {
      type = "Nullable(String)"
    }
    engine "distributed" {
      cluster_name    = "posthog_single_shard"
      remote_database = "posthog"
      remote_table    = "channel_definition"
    }
  }
}
