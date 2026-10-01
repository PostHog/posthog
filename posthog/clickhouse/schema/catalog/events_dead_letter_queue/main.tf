locals {
  deployment = merge({ exclude = [], overrides = {} }, var.deployment)
}

locals {
  storage = contains(local.deployment.components, "storage")
  write   = contains(local.deployment.components, "write")
  ingest  = contains(local.deployment.components, "ingest")
}
