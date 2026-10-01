moved {
  from = module.sharded_tophog
  to   = module.sharded_tophog_family.module.storage
}

moved {
  from = module.tophog
  to   = module.sharded_tophog_family.module.read
}

moved {
  from = module.writable_tophog
  to   = module.sharded_tophog_family.module.write
}

moved {
  from = module.tophog_mv
  to   = module.sharded_tophog_family.module.mv
}

moved {
  from = module.kafka_tophog
  to   = module.sharded_tophog_family.module.kafka
}
