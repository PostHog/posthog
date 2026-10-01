moved {
  from = module.error_tracking_issue_fingerprint_overrides
  to   = module.error_tracking_issue_fingerprint_overrides_family.module.storage
}

moved {
  from = module.writable_error_tracking_issue_fingerprint_overrides
  to   = module.error_tracking_issue_fingerprint_overrides_family.module.write
}

moved {
  from = module.raw_error_tracking_fingerprint_issue_state
  to   = module.raw_error_tracking_fingerprint_issue_state_family.module.storage
}

moved {
  from = module.error_tracking_fingerprint_issue_state
  to   = module.raw_error_tracking_fingerprint_issue_state_family.module.read
}

moved {
  from = module.writable_error_tracking_fingerprint_issue_state
  to   = module.raw_error_tracking_fingerprint_issue_state_family.module.write
}

moved {
  from = module.error_tracking_fingerprint_issue_state_mv
  to   = module.raw_error_tracking_fingerprint_issue_state_family.module.mv
}

moved {
  from = module.kafka_error_tracking_fingerprint_issue_state
  to   = module.raw_error_tracking_fingerprint_issue_state_family.module.kafka
}
