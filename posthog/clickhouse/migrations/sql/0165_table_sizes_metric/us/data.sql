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
