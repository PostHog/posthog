locals {
  deployment = merge({ exclude = [], overrides = {} }, var.deployment)
}

locals {
  storage = contains(local.deployment.components, "storage")
  read    = contains(local.deployment.components, "read")
  ingest  = contains(local.deployment.components, "ingest")
}
