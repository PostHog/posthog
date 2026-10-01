moved {
  from = module.clickhouse_cleanup_deleted_persons
  to   = module.clickhouse_cleanup_deleted_persons_family.module.storage
}

moved {
  from = module.clickhouse_cleanup_orphaned_distinct_ids
  to   = module.clickhouse_cleanup_orphaned_distinct_ids_family.module.storage
}

moved {
  from = module.clickhouse_cleanup_revived_distinct_ids
  to   = module.clickhouse_cleanup_revived_distinct_ids_family.module.storage
}

moved {
  from = module.clickhouse_cleanup_revived_persons
  to   = module.clickhouse_cleanup_revived_persons_family.module.storage
}
