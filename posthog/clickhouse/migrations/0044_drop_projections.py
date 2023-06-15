from posthog.clickhouse.client.migration_tools import run_sql_with_exceptions

operations = [
    run_sql_with_exceptions(
        "ALTER TABLE sharded_events DROP PROJECTION IF EXISTS fast_max_kafka_timestamp_sharded_events"
    ),
]
