import dagster

from dags import duplicate_pg_table

from . import resources

defs = dagster.Definitions(
    assets=[
        duplicate_pg_table.postgres_env_check,
    ],
    jobs=[
        duplicate_pg_table.duplicate_postgres_table_job,
    ],
    resources=resources,
)
