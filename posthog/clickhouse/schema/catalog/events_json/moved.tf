moved {
  from = module.sharded_events_json
  to   = module.sharded_events_json_family.module.storage
}

moved {
  from = module.events_json
  to   = module.sharded_events_json_family.module.read
}

moved {
  from = module.writable_events_json
  to   = module.sharded_events_json_family.module.write
}
