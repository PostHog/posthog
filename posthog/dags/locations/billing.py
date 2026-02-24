import dagster

from ee.billing.dags.job_switchers import job_switchers_daily_schedule, job_switchers_job, job_switchers_to_clay
from ee.billing.dags.productled_outbound_targets import (
    plo_base_targets,
    plo_daily_schedule,
    plo_job,
    plo_qualified_to_clay,
    qualify_signals,
)

from . import resources

defs = dagster.Definitions(
    assets=[job_switchers_to_clay, plo_base_targets, qualify_signals, plo_qualified_to_clay],
    jobs=[job_switchers_job, plo_job],
    schedules=[job_switchers_daily_schedule, plo_daily_schedule],
    resources=resources,
)
