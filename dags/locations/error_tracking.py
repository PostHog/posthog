import dagster

from django.conf import settings
from . import resources

from dags import (
    symbol_set_cleanup,
)


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

if settings.DEBUG:
    from dags import testing

    defs.jobs.append(testing.error)
