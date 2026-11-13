import dagster

from posthog.dags import distinct_id_usage, ingestion_assets, personhog_shadow_drift, personhog_shadow_lane

from . import loggers, resources

defs = dagster.Definitions(
    assets=[
        ingestion_assets.postgres_env_check,
    ],
    jobs=[
        distinct_id_usage.distinct_id_usage_monitoring,
        personhog_shadow_drift.personhog_shadow_lane_stop_and_compare_job,
        personhog_shadow_lane.personhog_shadow_lane_start_job,
    ],
    schedules=[
        distinct_id_usage.distinct_id_usage_monitoring_schedule,
    ],
    loggers=loggers,
    resources=resources,
)
