CREATE TABLE IF NOT EXISTS sharded_log_entries 
(
    team_id UInt64,
    -- The name of the service or product that generated the logs.
    -- Examples: batch_exports
    log_source LowCardinality(String),
    -- An id for the log source.
    -- Set log_source to avoid collision with ids from other log sources if the id generation is not safe.
    -- Examples: A batch export id, a cronjob id, a plugin id.
    log_source_id String,
    -- A secondary id e.g. for the instance of log_source that generated this log.
    -- This may be ommitted if log_source is a singleton.
    -- Examples: A batch export run id, a plugin_config id, a thread id, a process id, a machine id.
    instance_id String,
    -- Timestamp indicating when the log was generated.
    timestamp DateTime64(6, 'UTC'),
    -- The log level.
    -- Examples: INFO, WARNING, DEBUG, ERROR.
    level LowCardinality(String),
    -- The actual log message.
    message String
    
, _timestamp DateTime
, _offset UInt64

) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/{shard}/posthog.sharded_log_entries', '{replica}', _timestamp)
PARTITION BY toYYYYMMDD(timestamp) ORDER BY (team_id, log_source, log_source_id, instance_id, timestamp)
TTL toDate(timestamp) + INTERVAL 90 DAY
SETTINGS index_granularity=1024, ttl_only_drop_parts = 1

CREATE TABLE IF NOT EXISTS writable_log_entries 
(
    team_id UInt64,
    -- The name of the service or product that generated the logs.
    -- Examples: batch_exports
    log_source LowCardinality(String),
    -- An id for the log source.
    -- Set log_source to avoid collision with ids from other log sources if the id generation is not safe.
    -- Examples: A batch export id, a cronjob id, a plugin id.
    log_source_id String,
    -- A secondary id e.g. for the instance of log_source that generated this log.
    -- This may be ommitted if log_source is a singleton.
    -- Examples: A batch export run id, a plugin_config id, a thread id, a process id, a machine id.
    instance_id String,
    -- Timestamp indicating when the log was generated.
    timestamp DateTime64(6, 'UTC'),
    -- The log level.
    -- Examples: INFO, WARNING, DEBUG, ERROR.
    level LowCardinality(String),
    -- The actual log message.
    message String
    
, _timestamp DateTime
, _offset UInt64

) ENGINE = Distributed('posthog', 'default', 'sharded_log_entries', rand())

CREATE TABLE IF NOT EXISTS distributed_log_entries 
(
    team_id UInt64,
    -- The name of the service or product that generated the logs.
    -- Examples: batch_exports
    log_source LowCardinality(String),
    -- An id for the log source.
    -- Set log_source to avoid collision with ids from other log sources if the id generation is not safe.
    -- Examples: A batch export id, a cronjob id, a plugin id.
    log_source_id String,
    -- A secondary id e.g. for the instance of log_source that generated this log.
    -- This may be ommitted if log_source is a singleton.
    -- Examples: A batch export run id, a plugin_config id, a thread id, a process id, a machine id.
    instance_id String,
    -- Timestamp indicating when the log was generated.
    timestamp DateTime64(6, 'UTC'),
    -- The log level.
    -- Examples: INFO, WARNING, DEBUG, ERROR.
    level LowCardinality(String),
    -- The actual log message.
    message String
    
, _timestamp DateTime
, _offset UInt64

) ENGINE = Distributed('posthog', 'default', 'sharded_log_entries', rand())

CREATE TABLE IF NOT EXISTS kafka_log_entries_v3 
(
    team_id UInt64,
    -- The name of the service or product that generated the logs.
    -- Examples: batch_exports
    log_source LowCardinality(String),
    -- An id for the log source.
    -- Set log_source to avoid collision with ids from other log sources if the id generation is not safe.
    -- Examples: A batch export id, a cronjob id, a plugin id.
    log_source_id String,
    -- A secondary id e.g. for the instance of log_source that generated this log.
    -- This may be ommitted if log_source is a singleton.
    -- Examples: A batch export run id, a plugin_config id, a thread id, a process id, a machine id.
    instance_id String,
    -- Timestamp indicating when the log was generated.
    timestamp DateTime64(6, 'UTC'),
    -- The log level.
    -- Examples: INFO, WARNING, DEBUG, ERROR.
    level LowCardinality(String),
    -- The actual log message.
    message String
    
) ENGINE = Kafka(msk_cluster, kafka_topic_list = 'log_entries', kafka_group_name = 'clickhouse_log_entries_v3', kafka_format = 'JSONEachRow')

    SETTINGS kafka_skip_broken_messages = 100

CREATE MATERIALIZED VIEW IF NOT EXISTS log_entries_v3_mv
    TO default.writable_log_entries
    AS SELECT
    team_id,
    log_source,
    log_source_id,
    instance_id,
    timestamp,
    level,
    message,
    _timestamp,
    _offset
    FROM default.kafka_log_entries_v3
    WHERE toDate(timestamp) <= today()
