CREATE OR REPLACE VIEW custom_metrics_server_crash
    AS
    SELECT
        'ClickHouseCustomMetric_ServerCrash' AS name,
        map('instance', hostname()) AS labels,
        count() AS value,
        'Number of server crashes for current date' AS help,
        'gauge' AS type
    FROM system.crash_log
    WHERE event_date = today()
    GROUP BY hostname()

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
