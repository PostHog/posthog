import dagster

from dags.llma.daily_metrics import metrics_daily

from . import resources

defs = dagster.Definitions(
    assets=[
        metrics_daily.llma_metrics_daily,
    ],
    jobs=[
        metrics_daily.llma_metrics_daily_job,
    ],
    schedules=[
        metrics_daily.llma_metrics_daily_schedule,
    ],
    resources=resources,
)
