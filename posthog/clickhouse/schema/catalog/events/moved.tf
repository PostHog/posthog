moved {
  from = module.sharded_events
  to   = module.sharded_events_family.module.storage
}

moved {
  from = module.events
  to   = module.sharded_events_family.module.read
}

moved {
  from = module.writable_events
  to   = module.sharded_events_family.module.write
}
