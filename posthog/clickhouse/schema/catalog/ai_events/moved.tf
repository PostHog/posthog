moved {
  from = module.sharded_ai_events
  to   = module.sharded_ai_events_family.module.storage
}

moved {
  from = module.ai_events
  to   = module.sharded_ai_events_family.module.read
}
