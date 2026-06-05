import dagster

from products.ai_observability.dags.daily_metrics.main import (
    llma_metrics_daily,
    llma_metrics_daily_job,
    llma_metrics_daily_schedule,
)

from . import loggers, resources

defs = dagster.Definitions(
    assets=[llma_metrics_daily],
    jobs=[
        llma_metrics_daily_job,
    ],
    schedules=[
        llma_metrics_daily_schedule,
    ],
    loggers=loggers,
    resources=resources,
)
