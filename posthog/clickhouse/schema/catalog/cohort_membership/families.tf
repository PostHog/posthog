module "cohort_membership_family" {
  source = "../../lib/table_family"

  name     = "cohort_membership"
  database = var.database
  layout   = "global"
  columns  = local.cohort_membership_columns
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["last_updated"]
    order_by    = "(team_id, cohort_id, person_id)"
  }
  sharding_key = ""
  kafka = {
    topic          = "cohort_membership_changed"
    consumer_group = "clickhouse_cohort_membership_changed"
    arguments      = "settings"
    columns = [
      { name = "team_id", type = "Int64" },
      { name = "cohort_id", type = "Int64" },
      { name = "person_id", type = "UUID" },
      { name = "status", type = "Enum8('entered' = 1, 'left' = 2, 'member' = 3, 'not_member' = 4)" },
      { name = "last_updated", type = "DateTime64(6)" },
    ]
    settings = {}
  }
  mv_select = <<-SQL
team_id,
    cohort_id,
    person_id,
    multiIf(status = 'member', 'entered', status = 'not_member', 'left', status) AS status,
    last_updated
  SQL
  deployment = merge({
    cluster          = "posthog"
    kafka_collection = "msk_cluster"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["cohort_membership", "writable_cohort_membership", "cohort_membership_mv", "kafka_cohort_membership"], name) }
  })
}
