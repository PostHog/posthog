CREATE TABLE IF NOT EXISTS sharded_preaggregation_results
(
    team_id Int64,
    job_id UUID,
    time_window_start DateTime64(6, 'UTC'),

    -- TTL: rows are automatically deleted during parts merges after expires_at, prefer not to use the default and set this directly
    expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY,

    -- Breakdown dimension (empty array for no breakdown)
    breakdown_value Array(String),

    -- Aggregate state column (uniqExact for compat with queries that use count(DISTINCT person_id))
    uniq_exact_state AggregateFunction(uniqExact, UUID)
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/{shard}/posthog.preaggregation_results', '{replica}')

PARTITION BY toYYYYMM(time_window_start)
ORDER BY (team_id, job_id, time_window_start, breakdown_value)
TTL expires_at
SETTINGS index_granularity=8192

CREATE TABLE IF NOT EXISTS preaggregation_results
(
    team_id Int64,
    job_id UUID,
    time_window_start DateTime64(6, 'UTC'),

    -- TTL: rows are automatically deleted during parts merges after expires_at, prefer not to use the default and set this directly
    expires_at DateTime64(6, 'UTC') DEFAULT now() + INTERVAL 7 DAY,

    -- Breakdown dimension (empty array for no breakdown)
    breakdown_value Array(String),

    -- Aggregate state column (uniqExact for compat with queries that use count(DISTINCT person_id))
    uniq_exact_state AggregateFunction(uniqExact, UUID)
) ENGINE = Distributed('posthog', 'default', 'sharded_preaggregation_results', sipHash64(job_id))
