from datetime import timedelta

import temporalio.workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.base import PostHogWorkflow
from posthog.temporal.forecast.inputs import (
    DEFAULT_LOOKBACK_WINDOW,
    BackfillForecastInputs,
    BackfillForecastWorkflowInputs,
    BackfillForecastWorkflowResult,
    FetchHistoricalDataInputs,
    ForecastWorkflowInputs,
    ForecastWorkflowResult,
    GenerateForecastInputs,
    StoreForecastInputs,
)

with temporalio.workflow.unsafe.imports_passed_through():
    from posthog.temporal.forecast.activities import (
        backfill_forecasts_activity,
        fetch_historical_data_activity,
        generate_forecast_activity,
        store_forecast_result_activity,
    )


@temporalio.workflow.defn(name="forecast-generation")
class ForecastGenerationWorkflow(PostHogWorkflow):
    """
    Temporal workflow for generating time series forecasts for alert evaluation.

    This workflow:
    1. Fetches historical data from the insight
    2. Generates probabilistic forecasts using Chronos-Bolt
    3. Stores the forecast results for alert evaluation
    """

    @staticmethod
    def parse_inputs(inputs: list[str]):
        return ForecastWorkflowInputs(
            team_id=int(inputs[0]),
            alert_id=inputs[1],
            insight_id=int(inputs[2]),
            series_indices=[int(x) for x in inputs[3].split(",")],
            confidence_level=float(inputs[4]) if len(inputs) > 4 else 0.95,
            forecast_horizon=int(inputs[5]) if len(inputs) > 5 else 1,
            min_historical_points=int(inputs[6]) if len(inputs) > 6 else 14,
            lookback_window=int(inputs[7]) if len(inputs) > 7 else DEFAULT_LOOKBACK_WINDOW,
        )

    @temporalio.workflow.run
    async def run(self, inputs: ForecastWorkflowInputs) -> ForecastWorkflowResult:
        historical_data = await temporalio.workflow.execute_activity(
            fetch_historical_data_activity,
            FetchHistoricalDataInputs(
                team_id=inputs.team_id,
                insight_id=inputs.insight_id,
                series_indices=inputs.series_indices,
                min_historical_points=inputs.min_historical_points,
                lookback_window=inputs.lookback_window,
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        if not historical_data:
            return ForecastWorkflowResult(
                success=False,
                forecast_count=0,
                error="No valid historical data found for any series",
            )

        forecasts = await temporalio.workflow.execute_activity(
            generate_forecast_activity,
            GenerateForecastInputs(
                historical_data=historical_data,
                confidence_level=inputs.confidence_level,
                forecast_horizon=inputs.forecast_horizon,
            ),
            start_to_close_timeout=timedelta(minutes=30),
            heartbeat_timeout=timedelta(minutes=2),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )

        if not forecasts:
            return ForecastWorkflowResult(
                success=False,
                forecast_count=0,
                error="Failed to generate forecasts",
            )

        stored_count = await temporalio.workflow.execute_activity(
            store_forecast_result_activity,
            StoreForecastInputs(
                team_id=inputs.team_id,
                alert_id=inputs.alert_id,
                forecasts=forecasts,
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        return ForecastWorkflowResult(
            success=True,
            forecast_count=stored_count,
        )


@temporalio.workflow.defn(name="forecast-backfill")
class ForecastBackfillWorkflow(PostHogWorkflow):
    """
    Temporal workflow for backfilling historical forecast evaluations.

    This workflow:
    1. Fetches all historical data from the insight
    2. Generates forecasts for each historical point using only data available at that time
    3. Creates AlertCheck records marked as backfill
    4. Creates ForecastResult records for visualization
    """

    @staticmethod
    def parse_inputs(inputs: list[str]):
        return BackfillForecastWorkflowInputs(
            team_id=int(inputs[0]),
            alert_id=inputs[1],
            insight_id=int(inputs[2]),
            series_index=int(inputs[3]),
            confidence_level=float(inputs[4]) if len(inputs) > 4 else 0.95,
            max_forecasts=int(inputs[5]) if len(inputs) > 5 else DEFAULT_LOOKBACK_WINDOW,
            min_context=int(inputs[6]) if len(inputs) > 6 else 14,
            lookback_window=int(inputs[7]) if len(inputs) > 7 else DEFAULT_LOOKBACK_WINDOW,
        )

    @temporalio.workflow.run
    async def run(self, inputs: BackfillForecastWorkflowInputs) -> BackfillForecastWorkflowResult:
        # First fetch all historical data
        historical_data = await temporalio.workflow.execute_activity(
            fetch_historical_data_activity,
            FetchHistoricalDataInputs(
                team_id=inputs.team_id,
                insight_id=inputs.insight_id,
                series_indices=[inputs.series_index],
                min_historical_points=inputs.min_context + 1,
                lookback_window=10000,  # Fetch all data for backfill, we'll apply window per-forecast
            ),
            start_to_close_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        if not historical_data:
            return BackfillForecastWorkflowResult(
                success=False,
                forecasts_created=0,
                checks_created=0,
                error="No valid historical data found for backfill",
            )

        series_data = historical_data[0]

        # Run the backfill activity
        result = await temporalio.workflow.execute_activity(
            backfill_forecasts_activity,
            BackfillForecastInputs(
                team_id=inputs.team_id,
                alert_id=inputs.alert_id,
                series_index=inputs.series_index,
                confidence_level=inputs.confidence_level,
                historical_values=series_data["values"],
                timestamps=series_data["timestamps"],
                breakdown_value=series_data.get("breakdown_value"),
                max_forecasts=inputs.max_forecasts,
                min_context=inputs.min_context,
                lookback_window=inputs.lookback_window,
            ),
            start_to_close_timeout=timedelta(minutes=60),  # Backfill can take a while
            heartbeat_timeout=timedelta(minutes=5),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

        return BackfillForecastWorkflowResult(
            success=True,
            forecasts_created=result["forecasts_created"],
            checks_created=result["checks_created"],
        )
