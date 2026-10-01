# Reads from events. Those must exist on the node first.

locals {
  storage = contains(var.components, "storage")
  read    = contains(var.components, "read")
  write   = contains(var.components, "write")
}
