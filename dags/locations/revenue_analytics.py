import dagster

from . import resources

from dags import (
    exchange_rate,
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
    resources=resources,
)
