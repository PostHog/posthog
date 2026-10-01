locals {
  storage = contains(var.components, "storage")
  write   = contains(var.components, "write")
  ingest  = contains(var.components, "ingest")
}
