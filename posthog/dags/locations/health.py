import dagster

from products.web_analytics.dags.no_live_events import no_live_events_check

from . import resources

defs = dagster.Definitions(
    jobs=[
        no_live_events_check.job,
    ],
    resources=resources,
)
