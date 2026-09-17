database "posthog" {
  table "_person_property_mutation_log_columns" {
    abstract = true
    column "team_id" { type = "Int64" }
    column "event_uuid" { type = "UUID" }
    column "properties" { type = "String" }
    column "ingested_at" { type = "DateTime('UTC')" }
  }
  table "person_property_mutation_log" {
    extend = "_person_property_mutation_log_columns"
    engine "distributed" {
      cluster_name = "aux"
      remote_database = "posthog"
      remote_table = "person_property_mutation_log_data"
    }
  }
}
