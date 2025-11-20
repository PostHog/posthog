import dagster

from dags import delete_persons_from_trigger_log_job, ingestion_assets, persons_new_backfill

from . import resources

defs = dagster.Definitions(
    assets=[
        ingestion_assets.postgres_env_check,
    ],
    jobs=[
        persons_new_backfill.persons_new_backfill_job,
        delete_persons_from_trigger_log_job.delete_persons_from_trigger_log_job,
    ],
    resources=resources,
)
