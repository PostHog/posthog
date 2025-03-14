import os

DAGSTER_S3_BUCKET: str = os.getenv("DAGSTER_S3_BUCKET", "posthog-dags")
DAGSTER_DEFAULT_SLACK_ALERTS_CHANNEL: str = os.getenv("DAGSTER_DEFAULT_SLACK_ALERTS_CHANNEL", "#alerts-clickhouse")
DAGSTER_DATA_EXPORT_S3_BUCKET: str = os.getenv("DAGSTER_DATA_EXPORT_S3_BUCKET", "dagster-data-export")
