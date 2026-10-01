locals {
  storage = contains(var.components, "storage")
  read    = contains(var.components, "read")
  ingest  = contains(var.components, "ingest")

  # A dictionary source has no PASSWORD clause when the user has no password.
  dictionary_password_clause = var.dictionary_password == "" ? "" : " PASSWORD '${var.dictionary_password}'"
}
