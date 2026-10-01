locals {
  deployment = merge({ exclude = [], overrides = {} }, var.deployment)
}

terraform {
  required_providers {
    clickhousedbops = {
      source = "PostHog/clickhousedbops"
    }
  }
}

locals {
  storage = contains(local.deployment.components, "storage")
  read    = contains(local.deployment.components, "read")

  # A dictionary source has no PASSWORD clause when the user has no password.
  dictionary_password_clause = var.dictionary_password == "" ? "" : " PASSWORD '${var.dictionary_password}'"
}
