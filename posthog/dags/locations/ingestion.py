import dagster

from posthog.dags import detach_distinct_id, distinct_id_usage, ingestion_assets, person_property_reconciliation

from . import loggers, resources

defs = dagster.Definitions(
    assets=[
        ingestion_assets.postgres_env_check,
    ],
    jobs=[
        detach_distinct_id.detach_distinct_id_job,
        distinct_id_usage.distinct_id_usage_monitoring,
        person_property_reconciliation.person_property_reconciliation_job,
    ],
    schedules=[
        distinct_id_usage.distinct_id_usage_monitoring_schedule,
    ],
    sensors=[
        person_property_reconciliation.person_property_reconciliation_scheduler,
    ],
    loggers=loggers,
    resources=resources,
)
