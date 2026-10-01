moved {
  from = module.sharded_precalculated_events
  to   = module.sharded_precalculated_events_family.module.storage
}

moved {
  from = module.precalculated_events
  to   = module.sharded_precalculated_events_family.module.read
}

moved {
  from = module.writable_precalculated_events
  to   = module.sharded_precalculated_events_family.module.write
}

moved {
  from = module.precalculated_events_mv
  to   = module.sharded_precalculated_events_family.module.mv
}

moved {
  from = module.kafka_precalculated_events
  to   = module.sharded_precalculated_events_family.module.kafka
}

moved {
  from = module.sharded_precalculated_person_properties
  to   = module.sharded_precalculated_person_properties_family.module.storage
}

moved {
  from = module.precalculated_person_properties
  to   = module.sharded_precalculated_person_properties_family.module.read
}

moved {
  from = module.writable_precalculated_person_properties
  to   = module.sharded_precalculated_person_properties_family.module.write
}

moved {
  from = module.precalculated_person_properties_mv
  to   = module.sharded_precalculated_person_properties_family.module.mv
}

moved {
  from = module.kafka_precalculated_person_properties
  to   = module.sharded_precalculated_person_properties_family.module.kafka
}
