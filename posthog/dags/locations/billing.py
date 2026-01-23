import dagster

from ee.billing.dags.job_switchers import job_switchers_daily_schedule, job_switchers_job, job_switchers_to_clay

from . import resources

defs = dagster.Definitions(
    assets=[job_switchers_to_clay],
    jobs=[job_switchers_job],
    schedules=[job_switchers_daily_schedule],
    resources=resources,
)
