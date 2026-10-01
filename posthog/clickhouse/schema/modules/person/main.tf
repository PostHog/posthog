# Reads from person_distinct_id. Those must exist on the node first.

locals {
  storage = contains(var.components, "storage")
  read    = contains(var.components, "read")
  write   = contains(var.components, "write")
  ingest  = contains(var.components, "ingest")
}
