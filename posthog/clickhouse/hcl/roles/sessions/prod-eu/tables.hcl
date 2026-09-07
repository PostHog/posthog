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
  # prod-eu materializes eight properties prod-us does not.
  patch_table "events" {
    column "mat_$ai_experiment_id" {
      type    = "Nullable(String)"
      comment = "column_materializer::properties::$ai_experiment_id"
      after   = "mat_$ai_prompt_name"
    }
  }
}
