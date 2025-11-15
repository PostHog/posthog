import dagster

from dags import persons_new_backfill

from . import resources

defs = dagster.Definitions(
    assets=[
        persons_new_backfill.postgres_env_check,
    ],
    jobs=[
        persons_new_backfill.persons_new_backfill_job,
    ],
    resources=resources,
)
