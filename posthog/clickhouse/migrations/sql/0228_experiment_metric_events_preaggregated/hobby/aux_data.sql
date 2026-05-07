CREATE TABLE IF NOT EXISTS experiment_metric_events_preaggregated
(
    team_id Int64,
    job_id UUID,

    -- Per-event data
    entity_id String,
    timestamp DateTime64(6, 'UTC'),
    event_uuid UUID,
    session_id String,

    -- Mean/ratio metrics store the computed value here (default 0 for funnels)
    numeric_value Float64 DEFAULT 0,

    -- Funnel metrics store step indicators here (default empty for non-funnels)
    -- e.g. [1, 0, 1] means this event matches step_0 and step_2
    steps Array(UInt8) DEFAULT [],

    -- When this row was computed (used as ReplacingMergeTree version)
    computed_at DateTime64(6, 'UTC') DEFAULT now(),

    -- TTL: rows are automatically deleted after expires_at
    expires_at Date DEFAULT today() + INTERVAL 7 DAY
) ENGINE = Distributed('aux', 'default', 'sharded_experiment_metric_events_preaggregated', cityHash64(entity_id))
