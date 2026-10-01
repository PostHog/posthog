locals {
  storage = contains(var.components, "storage")
  read    = contains(var.components, "read")
}
