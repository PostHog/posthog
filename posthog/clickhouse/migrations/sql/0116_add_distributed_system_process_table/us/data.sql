CREATE TABLE IF NOT EXISTS distributed_system_processes 
        ENGINE = Distributed(posthog, system, processes)
        SETTINGS skip_unavailable_shards=1
