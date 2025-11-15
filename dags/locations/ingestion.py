import dagster

from dags import persons_new_backfill

from . import resources

defs = dagster.Definitions(
    jobs=[
        persons_new_backfill.persons_new_backfill_job,
    ],
    resources=resources,
)
