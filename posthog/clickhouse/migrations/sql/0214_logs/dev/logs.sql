CREATE TABLE IF NOT EXISTS default.logs AS default.logs32 ENGINE = Distributed('posthog_single_shard', 'default', 'logs32')
