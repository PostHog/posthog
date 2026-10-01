locals {
  deployment = merge({ exclude = [], overrides = {} }, var.deployment)
}

# Reads from events. Those must exist on the node first.

locals {
  storage = contains(local.deployment.components, "storage")
  read    = contains(local.deployment.components, "read")
  write   = contains(local.deployment.components, "write")
}
