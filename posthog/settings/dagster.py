import os

DAGSTER_S3_BUCKET: str = os.getenv("DAGSTER_S3_BUCKET", "posthog-dags")
DAGSTER_DEFAULT_SLACK_ALERTS_CHANNEL: str = os.getenv("DAGSTER_DEFAULT_SLACK_ALERTS_CHANNEL", "#alerts-clickhouse")
DAGSTER_DATA_EXPORT_S3_BUCKET: str = os.getenv("DAGSTER_DATA_EXPORT_S3_BUCKET", "dagster-data-export")
CLICKHOUSE_BACKUPS_BUCKET: str | None = os.getenv("CLICKHOUSE_BACKUPS_BUCKET")

CLICKHOUSE_FULL_BACKUP_SCHEDULE: str = os.getenv("CLICKHOUSE_FULL_BACKUP_SCHEDULE", "0 22 * * 5")
CLICKHOUSE_INCREMENTAL_BACKUP_SCHEDULE: str = os.getenv("CLICKHOUSE_INCREMENTAL_BACKUP_SCHEDULE", "0 22 * * 0-4,6")
SQUASH_PERSON_OVERRIDES_SCHEDULE: str = os.getenv("SQUASH_PERSON_OVERRIDES_SCHEDULE", "0 22 * * 6")  # At 22:00 (10 PM) on Saturday
