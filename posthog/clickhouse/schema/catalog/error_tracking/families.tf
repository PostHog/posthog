module "error_tracking_issue_fingerprint_overrides_family" {
  source = "../../lib/table_family"

  name     = "error_tracking_issue_fingerprint_overrides"
  database = var.database
  layout   = "global"
  columns  = local.error_tracking_issue_fingerprint_overrides_columns
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["version"]
    order_by    = "(team_id, fingerprint)"
    settings    = "index_granularity = 512"
    indexes = [
      { name = "kafka_timestamp_minmax_error_tracking_issue_fingerprint_overrides", expression = "_timestamp", type = "minmax", granularity = 3 },
    ]
  }
  routing = {
    write = true
  }
  sharding_key = ""
  deployment = merge({
    cluster = "posthog"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["error_tracking_issue_fingerprint_overrides", "writable_error_tracking_issue_fingerprint_overrides"], name) }
  })
}

module "raw_error_tracking_fingerprint_issue_state_family" {
  source = "../../lib/table_family"

  name     = "error_tracking_fingerprint_issue_state"
  database = var.database
  layout   = "global"
  columns  = local.raw_error_tracking_fingerprint_issue_state_columns
  storage = {
    engine      = "ReplacingMergeTree"
    engine_args = ["version"]
    order_by    = "(team_id, fingerprint)"
    settings    = "index_granularity = 512"
    indexes = [
      { name = "kafka_timestamp_minmax_raw_error_tracking_fingerprint_issue_state", expression = "_timestamp", type = "minmax", granularity = 3 },
    ]
  }
  routing = {
    read = true
  }
  sharding_key = ""
  kafka = {
    topic          = "clickhouse_error_tracking_fingerprint_issue_state"
    consumer_group = "clickhouse-error-tracking-fingerprint-issue-state"
    arguments      = "settings"
    columns        = local.kafka_error_tracking_fingerprint_issue_state_columns
    settings       = {}
  }
  mv_select = <<-SQL
team_id,
    fingerprint,
    issue_id,
    issue_name,
    issue_description,
    issue_status,
    issue_severity,
    assigned_user_id,
    assigned_role_id,
    first_seen,
    is_deleted,
    version,
    _timestamp,
    _offset,
    _partition
  SQL
  deployment = merge({
    cluster          = "aux"
    write_cluster    = "aux"
    kafka_collection = "msk_cluster"
    }, local.deployment, {
    components = setsubtract(local.deployment.components, ["test"])
    overrides  = { for name, override in local.deployment.overrides : name => override if contains(["raw_error_tracking_fingerprint_issue_state", "error_tracking_fingerprint_issue_state", "writable_error_tracking_fingerprint_issue_state", "error_tracking_fingerprint_issue_state_mv", "kafka_error_tracking_fingerprint_issue_state"], name) }
  })
  names = { storage = "raw_error_tracking_fingerprint_issue_state" }
}
