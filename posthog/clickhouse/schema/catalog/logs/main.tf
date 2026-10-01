locals {
  deployment = merge({ exclude = [], overrides = {} }, var.deployment)
}

locals {
  storage = contains(local.deployment.components, "storage")
  read    = contains(local.deployment.components, "read")
  write   = contains(local.deployment.components, "write")
  ingest  = contains(local.deployment.components, "ingest")
  test    = contains(local.deployment.components, "test")
}
