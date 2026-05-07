ALTER TABLE sharded_session_replay_events
        ADD COLUMN IF NOT EXISTS ai_tags_fixed SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
        ADD COLUMN IF NOT EXISTS ai_tags_freeform SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
        ADD COLUMN IF NOT EXISTS ai_highlighted SimpleAggregateFunction(max, UInt8) DEFAULT 0

ALTER TABLE session_replay_events
        ADD COLUMN IF NOT EXISTS ai_tags_fixed SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
        ADD COLUMN IF NOT EXISTS ai_tags_freeform SimpleAggregateFunction(groupUniqArrayArray, Array(String)),
        ADD COLUMN IF NOT EXISTS ai_highlighted SimpleAggregateFunction(max, UInt8) DEFAULT 0
