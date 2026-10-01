moved {
  from = module.sharded_usage_report_events_preagg
  to   = module.sharded_usage_report_events_preagg_family.module.storage
}

moved {
  from = module.usage_report_events_preagg
  to   = module.sharded_usage_report_events_preagg_family.module.read
}

moved {
  from = module.writable_usage_report_events_preagg
  to   = module.sharded_usage_report_events_preagg_family.module.write
}
