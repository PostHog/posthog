import dagster

from products.marketing_analytics.dags import mmm

from . import loggers, resources

jobs = []
# Marketing mix modeling processes internal PostHog data that only exists on Cloud US (team 2),
# so the job is not registered on Cloud EU (mirrors identity matching).
if mmm.is_mmm_registered():
    jobs.append(mmm.mmm_job)

defs = dagster.Definitions(
    jobs=jobs,
    loggers=loggers,
    resources=resources,
)
