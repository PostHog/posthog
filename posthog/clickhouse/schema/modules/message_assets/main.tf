locals {
  storage = contains(var.components, "storage")
  read    = contains(var.components, "read")
  ingest  = contains(var.components, "ingest")
}
