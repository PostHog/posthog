moved {
  from = module.sharded_session_replay_embeddings
  to   = module.sharded_session_replay_embeddings_family.module.storage
}

moved {
  from = module.session_replay_embeddings
  to   = module.sharded_session_replay_embeddings_family.module.read
}

moved {
  from = module.writable_session_replay_embeddings
  to   = module.sharded_session_replay_embeddings_family.module.write
}

moved {
  from = module.sharded_session_replay_events
  to   = module.sharded_session_replay_events_family.module.storage
}

moved {
  from = module.session_replay_events
  to   = module.sharded_session_replay_events_family.module.read
}

moved {
  from = module.writable_session_replay_events
  to   = module.sharded_session_replay_events_family.module.write
}

moved {
  from = module.sharded_session_replay_features
  to   = module.sharded_session_replay_features_family.module.storage
}

moved {
  from = module.session_replay_features
  to   = module.sharded_session_replay_features_family.module.read
}

moved {
  from = module.writable_session_replay_features
  to   = module.sharded_session_replay_features_family.module.write
}
