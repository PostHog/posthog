import dagster

from posthog.dags import distinct_id_usage, ingestion_assets

from . import loggers, resources

defs = dagster.Definitions(
    assets=[
        ingestion_assets.postgres_env_check,
    ],
    jobs=[
        distinct_id_usage.distinct_id_usage_monitoring,
    ],
    schedules=[
        distinct_id_usage.distinct_id_usage_monitoring_schedule,
    ],
    loggers=loggers,
    resources=resources,
)
