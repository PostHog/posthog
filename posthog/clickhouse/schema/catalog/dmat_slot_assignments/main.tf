locals {
  deployment = merge({ exclude = [], overrides = {} }, var.deployment)
}

locals {
  test = contains(local.deployment.components, "test")

  # A dictionary source has no PASSWORD clause when the user has no password.
  dictionary_password_clause = var.dictionary_password == "" ? "" : " PASSWORD '${var.dictionary_password}'"
}
