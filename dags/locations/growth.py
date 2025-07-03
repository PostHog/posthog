import dagster

from django.conf import settings
from . import resources

from dags.common import job_status_metrics_sensors
from dags import (
    deletes,
    slack_alerts,
    oauth,
)


defs = dagster.Definitions(
    jobs=[
        oauth.oauth_clear_expired_oauth_tokens_job,
    ],
    schedules=[
        oauth.oauth_clear_expired_oauth_tokens_schedule,
    ],
    sensors=[
        deletes.run_deletes_after_squash,
        slack_alerts.notify_slack_on_failure,
        *job_status_metrics_sensors,
    ],
    resources=resources,
)

if settings.DEBUG:
    from dags import testing

    defs.jobs.append(testing.error)
