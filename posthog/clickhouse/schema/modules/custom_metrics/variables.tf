variable "database" {
  description = "Database the objects live in."
  type        = string
  default     = "posthog"
}

variable "components" {
  description = "Parts of the group to create on the target nodes: `read` = Distributed tables, views and dictionaries that queries read from. Components the group does not have are ignored."
  type        = set(string)
  default     = ["storage", "read", "write", "ingest"]
}

variable "exclude" {
  description = "Names of objects to leave out of the enabled components."
  type        = set(string)
  default     = []
}

variable "overrides" {
  description = "Per-object changes for nodes whose schema differs from the definition here, keyed by object name. `lib/table/main.tf` lists the keys."
  type        = any
  default     = {}
}
