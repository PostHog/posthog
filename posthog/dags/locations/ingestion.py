import dagster

from posthog.dags import (
    distinct_id_usage,
    geoip_backfill,
    geoip_backfill_resend,
    geoip_backfill_verify,
    ingestion_assets,
)

from . import loggers, resources

defs = dagster.Definitions(
    assets=[
        ingestion_assets.postgres_env_check,
    ],
    jobs=[
        distinct_id_usage.distinct_id_usage_monitoring,
        geoip_backfill.geoip_backfill_staging_job,
        geoip_backfill.cleanup_geoip_backfill_staging,
        geoip_backfill_resend.geoip_backfill_resend_job,
        geoip_backfill_resend.cleanup_geoip_backfill_resend,
        geoip_backfill_verify.geoip_backfill_verify_job,
    ],
    schedules=[
        distinct_id_usage.distinct_id_usage_monitoring_schedule,
    ],
    loggers=loggers,
    resources=resources,
)
