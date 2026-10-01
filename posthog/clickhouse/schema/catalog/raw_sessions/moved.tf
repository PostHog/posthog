moved {
  from = module.sharded_raw_sessions
  to   = module.sharded_raw_sessions_family.module.storage
}

moved {
  from = module.raw_sessions
  to   = module.sharded_raw_sessions_family.module.read
}

moved {
  from = module.writable_raw_sessions
  to   = module.sharded_raw_sessions_family.module.write
}

moved {
  from = module.sharded_raw_sessions_v3
  to   = module.sharded_raw_sessions_v3_family.module.storage
}

moved {
  from = module.raw_sessions_v3
  to   = module.sharded_raw_sessions_v3_family.module.read
}

moved {
  from = module.writable_raw_sessions_v3
  to   = module.sharded_raw_sessions_v3_family.module.write
}
