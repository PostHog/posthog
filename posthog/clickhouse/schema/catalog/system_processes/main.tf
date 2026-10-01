locals {
  deployment = merge({ exclude = [], overrides = {} }, var.deployment)
}

locals {
  read = contains(local.deployment.components, "read")
}
