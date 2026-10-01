locals {
  deployment = merge({ exclude = [], overrides = {} }, var.deployment)
}

locals {
  storage = contains(local.deployment.components, "storage")
}
