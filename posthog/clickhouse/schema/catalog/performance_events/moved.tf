moved {
  from = module.sharded_performance_events
  to   = module.sharded_performance_events_family.module.storage
}

moved {
  from = module.performance_events
  to   = module.sharded_performance_events_family.module.read
}

moved {
  from = module.writeable_performance_events
  to   = module.sharded_performance_events_family.module.write
}

moved {
  from = module.performance_events_mv
  to   = module.sharded_performance_events_family.module.mv
}

moved {
  from = module.kafka_performance_events
  to   = module.sharded_performance_events_family.module.kafka
}
