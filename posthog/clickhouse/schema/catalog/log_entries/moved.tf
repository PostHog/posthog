moved {
  from = module.log_entries_data
  to   = module.log_entries_data_family.module.storage
}

moved {
  from = module.log_entries_distributed
  to   = module.log_entries_data_family.module.read
}

moved {
  from = module.writable_log_entries_aux
  to   = module.log_entries_data_family.module.write
}

moved {
  from = module.sharded_log_entries
  to   = module.sharded_log_entries_family.module.storage
}

moved {
  from = module.log_entries
  to   = module.sharded_log_entries_family.module.read
}

moved {
  from = module.writable_log_entries
  to   = module.sharded_log_entries_family.module.write
}
