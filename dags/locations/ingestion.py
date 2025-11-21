import dagster

from dags import delete_persons_from_trigger_log, ingestion_assets, persons_new_backfill

from . import resources

defs = dagster.Definitions(
    assets=[
        ingestion_assets.postgres_env_check,
    ],
    jobs=[
        delete_persons_from_trigger_log.delete_persons_from_trigger_log_job,
        persons_new_backfill.persons_new_backfill_job,
    ],
    resources=resources,
)
