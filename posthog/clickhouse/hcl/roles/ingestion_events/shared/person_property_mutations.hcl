database "posthog" {
  table "kafka_person_property_mutation_log" {
    column "team_id" { type = "Int64" }
    column "uuid" { type = "UUID" }
    column "properties" { type = "String" }
    engine "kafka" {
      collection = "warpstream_ingestion"
      topic_list = "clickhouse_events_json"
      group_name = "clickhouse_person_property_mutation_log"
      format = "JSONEachRow"
      skip_broken_messages = 100
    }
  }
  materialized_view "person_property_mutation_log_mv" {
    to_table = "posthog.person_property_mutation_log"
    query = file("sql/person_property_mutation_log_mv.sql")
    column "team_id" { type = "Int64" }
    column "event_uuid" { type = "UUID" }
    column "properties" { type = "String" }
    column "ingested_at" { type = "DateTime('UTC')" }
  }
}
