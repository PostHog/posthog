# Production objects from before this catalogue, declared from their live definitions. Only Cloud roots
# in posthog-cloud-infra list them.

variable "node" {
  type    = any
  default = null
}

variable "database" {
  type    = string
  default = "posthog"
}

variable "objects" {
  description = "Names of the objects to create."
  type        = set(string)
}

variable "test" {
  description = "Use the definitions the test suite expects."
  type        = bool
  default     = false
}

variable "deployment" { type = any }

locals {
  deployment = merge({ overrides = {} }, var.deployment)
}

module "session_recording_events" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "session_recording_events")
  database = var.database
  name     = "session_recording_events"
  override = try(local.deployment.overrides["session_recording_events"], {})
  engine   = "Distributed('${var.database}', '${var.database}', 'sharded_session_recording_events', sipHash64(distinct_id))"
  columns = [
    { name = "uuid", type = "UUID" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "session_id", type = "String" },
    { name = "window_id", type = "String" },
    { name = "snapshot_data", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
    { name = "has_full_snapshot", type = "Int8", comment = "column_materializer::has_full_snapshot" },
    { name = "events_summary", type = "Array(String)", comment = "column_materializer::events_summary" },
    { name = "click_count", type = "Int8", comment = "column_materializer::click_count" },
    { name = "keypress_count", type = "Int8", comment = "column_materializer::keypress_count" },
    { name = "timestamps_summary", type = "Array(DateTime64(6, 'UTC'))", comment = "column_materializer::timestamps_summary" },
    { name = "first_event_timestamp", type = "DateTime64(6, 'UTC')", comment = "column_materializer::first_event_timestamp" },
    { name = "last_event_timestamp", type = "DateTime64(6, 'UTC')", comment = "column_materializer::last_event_timestamp" },
    { name = "urls", type = "Array(String)", comment = "column_materializer::urls" },
  ]
}

module "writable_session_recording_events" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "writable_session_recording_events")
  database = var.database
  name     = "writable_session_recording_events"
  override = try(local.deployment.overrides["writable_session_recording_events"], {})
  engine   = "Distributed('${var.database}', '${var.database}', 'sharded_session_recording_events', sipHash64(distinct_id))"
  columns = [
    { name = "uuid", type = "UUID" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "session_id", type = "String" },
    { name = "window_id", type = "String" },
    { name = "snapshot_data", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')" },
    { name = "_timestamp", type = "DateTime" },
    { name = "_offset", type = "UInt64" },
  ]
}
