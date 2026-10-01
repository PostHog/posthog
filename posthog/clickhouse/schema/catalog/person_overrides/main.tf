locals {
  deployment = merge({ exclude = [], overrides = {} }, var.deployment)
}

locals {
  storage = contains(local.deployment.components, "storage")
  read    = contains(local.deployment.components, "read")
  ingest  = contains(local.deployment.components, "ingest")

  # A dictionary source has no PASSWORD clause when the user has no password.
  dictionary_password_clause = var.dictionary_password == "" ? "" : " PASSWORD '${var.dictionary_password}'"
}
