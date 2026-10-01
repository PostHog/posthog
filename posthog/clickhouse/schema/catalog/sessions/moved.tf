moved {
  from = module.sharded_sessions
  to   = module.sharded_sessions_family.module.storage
}

moved {
  from = module.sessions
  to   = module.sharded_sessions_family.module.read
}

moved {
  from = module.writable_sessions
  to   = module.sharded_sessions_family.module.write
}
