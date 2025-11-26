from posthog.temporal.forecast.activities import (
    backfill_forecasts_activity,
    fetch_historical_data_activity,
    generate_forecast_activity,
    store_forecast_result_activity,
)
from posthog.temporal.forecast.workflows import ForecastBackfillWorkflow, ForecastGenerationWorkflow

WORKFLOWS = [ForecastGenerationWorkflow, ForecastBackfillWorkflow]
ACTIVITIES = [
    backfill_forecasts_activity,
    fetch_historical_data_activity,
    generate_forecast_activity,
    store_forecast_result_activity,
]
