moved {
  from = module.sharded_distinct_id_usage
  to   = module.sharded_distinct_id_usage_family.module.storage
}

moved {
  from = module.distinct_id_usage
  to   = module.sharded_distinct_id_usage_family.module.read
}

moved {
  from = module.writable_distinct_id_usage
  to   = module.sharded_distinct_id_usage_family.module.write
}

moved {
  from = module.distinct_id_usage_mv
  to   = module.sharded_distinct_id_usage_family.module.mv
}

moved {
  from = module.kafka_distinct_id_usage
  to   = module.sharded_distinct_id_usage_family.module.kafka
}
