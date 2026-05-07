CREATE TABLE IF NOT EXISTS writable_heatmaps
(
    session_id VARCHAR,
    team_id Int64,
    distinct_id VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    -- x is the x with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    x Int16,
    -- y is the y with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    y Int16,
    -- stored so that in future we can support other resolutions
    scale_factor Int16,
    viewport_width Int16,
    viewport_height Int16,
    -- some elements move when the page scrolls, others do not
    pointer_target_fixed Bool,
    current_url VARCHAR,
    type LowCardinality(String),
    _timestamp DateTime,
    _offset UInt64,
    _partition UInt64
) ENGINE = Distributed('posthog', 'default', 'sharded_heatmaps', cityHash64(concat(toString(team_id), '-', session_id, '-', toString(toDate(timestamp)))))

CREATE TABLE IF NOT EXISTS heatmaps
(
    session_id VARCHAR,
    team_id Int64,
    distinct_id VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    -- x is the x with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    x Int16,
    -- y is the y with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    y Int16,
    -- stored so that in future we can support other resolutions
    scale_factor Int16,
    viewport_width Int16,
    viewport_height Int16,
    -- some elements move when the page scrolls, others do not
    pointer_target_fixed Bool,
    current_url VARCHAR,
    type LowCardinality(String),
    _timestamp DateTime,
    _offset UInt64,
    _partition UInt64
) ENGINE = Distributed('posthog', 'default', 'sharded_heatmaps', cityHash64(concat(toString(team_id), '-', session_id, '-', toString(toDate(timestamp)))))

CREATE TABLE IF NOT EXISTS sharded_heatmaps
(
    session_id VARCHAR,
    team_id Int64,
    distinct_id VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    -- x is the x with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    x Int16,
    -- y is the y with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    y Int16,
    -- stored so that in future we can support other resolutions
    scale_factor Int16,
    viewport_width Int16,
    viewport_height Int16,
    -- some elements move when the page scrolls, others do not
    pointer_target_fixed Bool,
    current_url VARCHAR,
    type LowCardinality(String),
    _timestamp DateTime,
    _offset UInt64,
    _partition UInt64
) ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/posthog.heatmaps', '{replica}')

    PARTITION BY toYYYYMM(timestamp)
    -- almost always this is being queried by
    --   * type,
    --   * team_id,
    --   * date range,
    --   * URL (maybe matching wild cards),
    --   * width
    -- we'll almost never query this by session id
    -- so from least to most cardinality that's
    ORDER BY (type, team_id,  toDate(timestamp), current_url, viewport_width)
    TTL toDate(timestamp) + INTERVAL 90 DAY
-- I am purposefully not setting index granularity
-- the default is 8192, and we will be loading a lot of data
-- per query, we tend to copy this 512 around the place but
-- i don't think it applies here

CREATE TABLE IF NOT EXISTS kafka_heatmaps
(
    session_id VARCHAR,
    team_id Int64,
    distinct_id VARCHAR,
    timestamp DateTime64(6, 'UTC'),
    -- x is the x with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    x Int16,
    -- y is the y with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    y Int16,
    -- stored so that in future we can support other resolutions
    scale_factor Int16,
    viewport_width Int16,
    viewport_height Int16,
    -- some elements move when the page scrolls, others do not
    pointer_target_fixed Bool,
    current_url VARCHAR,
    type LowCardinality(String)
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'clickhouse_heatmap_events', kafka_group_name = 'group1', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS heatmaps_mv
TO default.writable_heatmaps
AS SELECT
    session_id,
    team_id,
    distinct_id,
    timestamp,
    -- x is the x with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    x,
    -- y is the y with resolution applied, the resolution converts high fidelity mouse positions into an NxN grid
    y,
    -- stored so that in future we can support other resolutions
    scale_factor,
    viewport_width,
    viewport_height,
    -- some elements move when the page scrolls, others do not
    pointer_target_fixed,
    current_url,
    type,
    _timestamp,
    _offset,
    _partition
FROM default.kafka_heatmaps
