moved {
  from = module.duplicate_events
  to   = module.duplicate_events_family.module.storage
}

moved {
  from = module.writable_duplicate_events
  to   = module.duplicate_events_family.module.write
}

moved {
  from = module.duplicate_events_mv
  to   = module.duplicate_events_family.module.mv
}

moved {
  from = module.kafka_duplicate_events
  to   = module.duplicate_events_family.module.kafka
}
