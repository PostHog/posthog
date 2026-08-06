import dagster

from posthog.dags import backups

from . import loggers, resources

defs = dagster.Definitions(
    jobs=[
        backups.non_sharded_backup,
    ],
    schedules=[
        backups.full_logs_backup_schedule,
        backups.incremental_logs_backup_schedule,
    ],
    loggers=loggers,
    resources=resources,
)
