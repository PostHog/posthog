import dagster

from posthog.dags.common.health.jobs.web_analytics.no_live_events import no_live_events_check

from . import resources

defs = dagster.Definitions(
    jobs=[
        # Web Analytics
        no_live_events_check.job,
    ],
    resources=resources,
)
