moved {
  from = module.sharded_events_recent
  to   = module.sharded_events_recent_family.module.storage
}

moved {
  from = module.distributed_events_recent
  to   = module.sharded_events_recent_family.module.read
}

moved {
  from = module.writable_events_recent
  to   = module.sharded_events_recent_family.module.write
}
