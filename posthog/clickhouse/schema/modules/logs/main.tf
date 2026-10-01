locals {
  storage = contains(var.components, "storage")
  read    = contains(var.components, "read")
  write   = contains(var.components, "write")
  ingest  = contains(var.components, "ingest")
  test    = contains(var.components, "test")
}
