module "dmat_slot_assignments" {
  source              = "./dmat_slot_assignments"
  database            = var.database
  deployment          = try(var.deployment.families.dmat_slot_assignments, { components = [] })
  dictionary_user     = var.dictionary_user
  dictionary_password = var.dictionary_password
}
