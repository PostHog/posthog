import os

DAGSTER_S3_BUCKET: str = os.getenv("DAGSTER_S3_BUCKET", "posthog-dags")
DAGSTER_DEFAULT_SLACK_ALERTS_CHANNEL: str = os.getenv("DAGSTER_DEFAULT_SLACK_ALERTS_CHANNEL", "#alerts-clickhouse")
DAGSTER_DATA_EXPORT_S3_BUCKET: str = os.getenv("DAGSTER_DATA_EXPORT_S3_BUCKET", "dagster-data-export")
CLICKHOUSE_BACKUPS_BUCKET: str = os.getenv("CLICKHOUSE_BACKUPS_BUCKET", "posthog-clickhouse-169684386827-us-east-1")
