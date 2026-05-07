CREATE OR REPLACE VIEW custom_metrics_table_sizes
    AS
    SELECT
        'ClickHouseCustomMetric_TableTotalBytes' AS name,
        map('instance', hostname(),
            'database', database,
            'table', table
        ) AS labels,
        total_bytes::Float64 AS value,
        'Size of a database table on a given node (need a sum for sharded)' AS help,
        'gauge' AS type
    FROM system.tables
    WHERE database NOT IN ('INFORMATION_SCHEMA', 'information_schema')
        AND total_bytes IS NOT NULL

CREATE OR REPLACE VIEW custom_metrics(
         name String,
         labels Map(String, String),
         value Float64,
         help String,
         type String
    )
    AS SELECT * REPLACE (toFloat64(value) as value)
    FROM custom_metrics_test
    UNION ALL
    SELECT * REPLACE (toFloat64(value) as value)
    FROM custom_metrics_replication_queue
    UNION ALL
    SELECT * REPLACE (toFloat64(value) as value)
    FROM custom_metrics_events_recent_lag
    UNION ALL SELECT * FROM custom_metrics_counters
UNION ALL SELECT * REPLACE (toFloat64(value) as value) FROM custom_metrics_server_crash
UNION ALL SELECT * FROM custom_metrics_table_sizes
