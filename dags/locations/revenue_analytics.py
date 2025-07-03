import dagster

from django.conf import settings
from . import resources

from dags.common import job_status_metrics_sensors
from dags import (
    exchange_rate,
    slack_alerts,
)

defs = dagster.Definitions(
    assets=[
        exchange_rate.daily_exchange_rates,
        exchange_rate.hourly_exchange_rates,
        exchange_rate.daily_exchange_rates_in_clickhouse,
        exchange_rate.hourly_exchange_rates_in_clickhouse,
    ],
    jobs=[
        exchange_rate.daily_exchange_rates_job,
        exchange_rate.hourly_exchange_rates_job,
    ],
    schedules=[
        exchange_rate.daily_exchange_rates_schedule,
        exchange_rate.hourly_exchange_rates_schedule,
    ],
    sensors=[
        slack_alerts.notify_slack_on_failure,
        *job_status_metrics_sensors,
    ],
    resources=resources,
)

if settings.DEBUG:
    from dags import testing

    defs.jobs.append(testing.error)
