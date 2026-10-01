# Kafka tables and the materialized views that consume them.

module "cohort_membership_mv" {
  source = "../../lib/materialized_view"

  enabled  = local.ingest && !contains(var.exclude, "cohort_membership_mv")
  database = var.database
  name     = "cohort_membership_mv"
  to_table = "${var.database}.writable_cohort_membership"
  query    = <<-SQL
    SELECT
        team_id,
        cohort_id,
        person_id,
        multiIf(status = 'member', 'entered', status = 'not_member', 'left', status) AS status,
        last_updated
    FROM ${var.database}.kafka_cohort_membership
  SQL
  override = try(var.overrides["cohort_membership_mv"], {})

  depends_on = [
    module.kafka_cohort_membership,
    module.writable_cohort_membership,
  ]
}

module "kafka_cohort_membership" {
  source = "../../lib/table"

  enabled  = local.ingest && !contains(var.exclude, "kafka_cohort_membership")
  database = var.database
  name     = "kafka_cohort_membership"
  engine   = "Kafka(msk_cluster)"
  settings = "kafka_format = 'JSONEachRow', kafka_group_name = 'clickhouse_cohort_membership_changed', kafka_topic_list = 'cohort_membership_changed'"
  columns = [
    { name = "team_id", type = "Int64" },
    { name = "cohort_id", type = "Int64" },
    { name = "person_id", type = "UUID" },
    { name = "status", type = "Enum8('entered' = 1, 'left' = 2, 'member' = 3, 'not_member' = 4)" },
    { name = "last_updated", type = "DateTime64(6)" },
  ]
  override = try(var.overrides["kafka_cohort_membership"], {})
}
