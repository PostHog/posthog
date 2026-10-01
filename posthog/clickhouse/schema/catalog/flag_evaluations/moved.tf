moved {
  from = module.sharded_flag_evaluations
  to   = module.sharded_flag_evaluations_family.module.storage
}

moved {
  from = module.flag_evaluations
  to   = module.sharded_flag_evaluations_family.module.read
}

moved {
  from = module.writable_flag_evaluations
  to   = module.sharded_flag_evaluations_family.module.write
}

moved {
  from = module.flag_evaluations_mv
  to   = module.sharded_flag_evaluations_family.module.mv
}

moved {
  from = module.kafka_flag_evaluations
  to   = module.sharded_flag_evaluations_family.module.kafka
}
