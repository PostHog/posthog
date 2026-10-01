moved {
  from = module.sharded_platform_alert_events
  to   = module.sharded_platform_alert_events_family.module.storage
}

moved {
  from = module.platform_alert_events
  to   = module.sharded_platform_alert_events_family.module.read
}
