variable "database" {
  description = "Database the objects live in."
  type        = string
  default     = "posthog"
}

variable "components" {
  description = "Parts of the group to create on the target nodes: `storage` = tables that hold data, and the materialized views between them; `read` = Distributed tables, views and dictionaries that queries read from; `write` = Distributed tables that inserts go through. Components the group does not have are ignored."
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

variable "zk_path_suffix" {
  description = "Appended to every replication path, so that a second copy of the schema on the same Keeper does not collide with the first."
  type        = string
  default     = ""
}

variable "ttl" {
  description = "Set table TTLs. Tests turn them off, because they insert rows with old timestamps."
  type        = bool
  default     = true
}
