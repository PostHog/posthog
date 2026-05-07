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

CREATE TABLE IF NOT EXISTS kafka_app_metrics2
(
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    app_source LowCardinality(String),
    app_source_id String,
    instance_id String,
    metric_kind String,
    metric_name String,
    count Int64
)
ENGINE=Kafka(msk_cluster, kafka_topic_list = 'clickhouse_app_metrics2', kafka_group_name = 'group1', kafka_format = 'JSONEachRow')

CREATE TABLE IF NOT EXISTS writable_app_metrics2
(
    team_id Int64,
    timestamp DateTime64(6, 'UTC'),
    -- The name of the service or product that generated the metrics.
    -- Examples: plugins, hog
    app_source LowCardinality(String),
    -- An id for the app source.
    -- Set app_source to avoid collision with ids from other app sources if the id generation is not safe.
    -- Examples: A plugin id, a hog application id
    app_source_id String,
    -- A secondary id e.g. for the instance of app_source that generated this metric.
    -- This may be ommitted if app_source is a singleton.
    -- Examples: A plugin config id, a hog application config id
    instance_id String,
    metric_kind LowCardinality(String),
    metric_name LowCardinality(String),
    count SimpleAggregateFunction(sum, Int64)
    
, _timestamp DateTime
, _offset UInt64
, _partition UInt64

)
ENGINE=Distributed('posthog', 'default', 'sharded_app_metrics2', rand())

CREATE MATERIALIZED VIEW IF NOT EXISTS app_metrics2_mv
TO writable_app_metrics2
AS SELECT
team_id,
timestamp,
app_source,
app_source_id,
instance_id,
metric_kind,
metric_name,
count,
_timestamp,
_offset,
_partition
FROM kafka_app_metrics2
