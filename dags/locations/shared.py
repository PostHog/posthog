import dagster

from django.conf import settings
from . import resources

from dags.common import job_status_metrics_sensors
from dags import (
    slack_alerts,
)

# Used for definitions that are shared between locations.
# Mainly sensors
defs = dagster.Definitions(
    sensors=[
        slack_alerts.notify_slack_on_failure,
        *job_status_metrics_sensors,
    ],
    resources=resources,
)

if settings.DEBUG:
    from dags import testing

    defs.jobs.append(testing.error)
