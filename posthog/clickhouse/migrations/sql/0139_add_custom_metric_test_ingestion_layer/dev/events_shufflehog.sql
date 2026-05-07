CREATE OR REPLACE VIEW custom_metrics_test
    AS SELECT
        'ClickHouseCustomMetric_Test' AS name,
        map('instance', hostname()) AS labels,
        1 AS value,
        'Test to check that the metric endpoint is working' AS help,
        'gauge' AS type

CREATE OR REPLACE VIEW custom_metrics
    AS SELECT * REPLACE (toFloat64(value) as value)
    FROM custom_metrics_test
