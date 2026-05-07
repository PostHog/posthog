CREATE TABLE IF NOT EXISTS sharded_experiment_exposures_preaggregated
(
    team_id Int64,
    job_id UUID,

    -- Per-entity exposure data
    entity_id String,
    variant String,
    first_exposure_time DateTime64(6, 'UTC'),
    last_exposure_time DateTime64(6, 'UTC'),
    exposure_event_uuid UUID,
    exposure_session_id String,

    -- Breakdown dimensions (empty array if no breakdown)
    breakdown_value Array(String),

    -- When this row was computed (used as ReplacingMergeTree version)
    computed_at DateTime64(6, 'UTC') DEFAULT now(),

    -- TTL: rows are automatically deleted after expires_at
    expires_at Date DEFAULT today() + INTERVAL 7 DAY
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.experiment_exposures_preaggregated', '{replica}', computed_at)

PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, job_id, entity_id, breakdown_value)
TTL expires_at
SETTINGS index_granularity=8192, ttl_only_drop_parts = 1

CREATE TABLE IF NOT EXISTS experiment_exposures_preaggregated
(
    team_id Int64,
    job_id UUID,

    -- Per-entity exposure data
    entity_id String,
    variant String,
    first_exposure_time DateTime64(6, 'UTC'),
    last_exposure_time DateTime64(6, 'UTC'),
    exposure_event_uuid UUID,
    exposure_session_id String,

    -- Breakdown dimensions (empty array if no breakdown)
    breakdown_value Array(String),

    -- When this row was computed (used as ReplacingMergeTree version)
    computed_at DateTime64(6, 'UTC') DEFAULT now(),

    -- TTL: rows are automatically deleted after expires_at
    expires_at Date DEFAULT today() + INTERVAL 7 DAY
) ENGINE = Distributed('posthog', 'default', 'sharded_experiment_exposures_preaggregated', cityHash64(entity_id))
