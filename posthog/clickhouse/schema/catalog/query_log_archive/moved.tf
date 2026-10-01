moved {
  from = module.query_log_archive_v2
  to   = module.query_log_archive_v2_family.module.storage
}

moved {
  from = module.sharded_query_log_archive
  to   = module.sharded_query_log_archive_family.module.storage
}

moved {
  from = module.query_log_archive
  to   = module.sharded_query_log_archive_family.module.read
}

moved {
  from = module.sharded_query_log_archive_old
  to   = module.sharded_query_log_archive_old_family.module.storage
}
