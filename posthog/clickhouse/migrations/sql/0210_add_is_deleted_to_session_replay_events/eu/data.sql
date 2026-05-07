ALTER TABLE session_replay_events
        ADD COLUMN IF NOT EXISTS is_deleted SimpleAggregateFunction(max, UInt8) DEFAULT 0

ALTER TABLE sharded_session_replay_events
        ADD COLUMN IF NOT EXISTS is_deleted SimpleAggregateFunction(max, UInt8) DEFAULT 0
