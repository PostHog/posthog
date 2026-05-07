CREATE TABLE IF NOT EXISTS kafka_heatmaps_ws
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
) ENGINE = Kafka(warpstream_ingestion, kafka_topic_list = 'clickhouse_heatmap_events', kafka_group_name = 'clickhouse_heatmaps_ws', kafka_format = 'JSONEachRow')

CREATE MATERIALIZED VIEW IF NOT EXISTS heatmaps_ws_mv
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
FROM default.kafka_heatmaps_ws
