import dagster

from dags import symbol_set_cleanup

from . import resources

defs = dagster.Definitions(
    assets=[
        symbol_set_cleanup.symbol_sets_to_delete,
        symbol_set_cleanup.symbol_set_cleanup_results,
    ],
    jobs=[
        symbol_set_cleanup.symbol_set_cleanup_job,
    ],
    schedules=[
        symbol_set_cleanup.daily_symbol_set_cleanup_schedule,
    ],
    resources=resources,
)
