moved {
  from = module.plugin_log_entries
  to   = module.plugin_log_entries_family.module.storage
}

moved {
  from = module.writable_plugin_log_entries
  to   = module.plugin_log_entries_family.module.write
}

moved {
  from = module.plugin_log_entries_mv
  to   = module.plugin_log_entries_family.module.mv
}

moved {
  from = module.kafka_plugin_log_entries
  to   = module.plugin_log_entries_family.module.kafka
}
