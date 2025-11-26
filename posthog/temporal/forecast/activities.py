from dataclasses import asdict
from datetime import UTC, datetime

import structlog
import temporalio.activity

from posthog.temporal.forecast.inputs import (
    BackfillForecastInputs,
    FetchHistoricalDataInputs,
    ForecastPrediction,
    GenerateForecastInputs,
    HistoricalDataResult,
    StoreForecastInputs,
)

logger = structlog.get_logger(__name__)


@temporalio.activity.defn
async def fetch_historical_data_activity(inputs: FetchHistoricalDataInputs) -> list[dict]:
    """
    Fetch historical time series data from the insight for the specified series.
    """
    from asgiref.sync import sync_to_async

    from posthog.hogql_queries.query_runner import get_query_runner
    from posthog.models import Insight

    logger.info(
        "Fetching historical data",
        team_id=inputs.team_id,
        insight_id=inputs.insight_id,
        series_indices=inputs.series_indices,
    )

    @sync_to_async
    def get_insight_data():
        insight = Insight.objects.select_related("team").get(id=inputs.insight_id, team_id=inputs.team_id)
        query = insight.query

        if query.get("source"):
            query = query["source"]

        runner = get_query_runner(query, insight.team)
        response = runner.calculate()
        return response.results

    results = await get_insight_data()

    historical_data = []
    for series_index in inputs.series_indices:
        if series_index >= len(results):
            logger.warning(
                "Series index out of range",
                series_index=series_index,
                total_series=len(results),
            )
            continue

        series = results[series_index]
        data = series.get("data", [])
        days = series.get("days", series.get("labels", []))
        breakdown_value = series.get("breakdown_value")

        # Apply lookback window - only use the most recent N points
        if len(data) > inputs.lookback_window:
            data = data[-inputs.lookback_window :]
            days = days[-inputs.lookback_window :]

        if len(data) < inputs.min_historical_points:
            logger.warning(
                "Insufficient historical data points",
                series_index=series_index,
                data_points=len(data),
                min_required=inputs.min_historical_points,
            )
            continue

        result = HistoricalDataResult(
            series_index=series_index,
            breakdown_value={"value": breakdown_value} if breakdown_value is not None else None,
            timestamps=days,
            values=[float(v) if v is not None else 0.0 for v in data],
        )
        historical_data.append(asdict(result))

    logger.info(
        "Historical data fetched",
        series_count=len(historical_data),
    )

    return historical_data


@temporalio.activity.defn
async def generate_forecast_activity(inputs: GenerateForecastInputs) -> list[dict]:
    """
    Generate forecasts using Chronos-Bolt for the provided historical data.
    """
    from posthog.temporal.forecast.chronos_service import ChronosForecaster

    logger.info(
        "Generating forecasts",
        series_count=len(inputs.historical_data),
        confidence_level=inputs.confidence_level,
        forecast_horizon=inputs.forecast_horizon,
    )

    forecasts = []

    if len(inputs.historical_data) == 1:
        series = inputs.historical_data[0]
        values = series["values"]

        predicted, lower, upper = ChronosForecaster.forecast(
            historical_values=values,
            prediction_length=inputs.forecast_horizon,
            confidence_level=inputs.confidence_level,
        )

        prediction = ForecastPrediction(
            series_index=series["series_index"],
            breakdown_value=series.get("breakdown_value"),
            forecast_timestamp=datetime.now(UTC).isoformat(),
            predicted_value=predicted,
            lower_bound=lower,
            upper_bound=upper,
            confidence_level=inputs.confidence_level,
            historical_data_hash=ChronosForecaster.compute_data_hash(values),
        )
        forecasts.append(asdict(prediction))
    else:
        historical_series = [s["values"] for s in inputs.historical_data]

        batch_results = ChronosForecaster.forecast_batch(
            historical_series=historical_series,
            prediction_length=inputs.forecast_horizon,
            confidence_level=inputs.confidence_level,
        )

        for i, (predicted, lower, upper) in enumerate(batch_results):
            series = inputs.historical_data[i]
            prediction = ForecastPrediction(
                series_index=series["series_index"],
                breakdown_value=series.get("breakdown_value"),
                forecast_timestamp=datetime.now(UTC).isoformat(),
                predicted_value=predicted,
                lower_bound=lower,
                upper_bound=upper,
                confidence_level=inputs.confidence_level,
                historical_data_hash=ChronosForecaster.compute_data_hash(series["values"]),
            )
            forecasts.append(asdict(prediction))

    logger.info(
        "Forecasts generated",
        forecast_count=len(forecasts),
    )

    return forecasts


@temporalio.activity.defn
async def store_forecast_result_activity(inputs: StoreForecastInputs) -> int:
    """
    Store forecast results in the database.
    """
    from django.db import transaction

    from asgiref.sync import sync_to_async

    from posthog.models.alert import AlertConfiguration, ForecastResult

    logger.info(
        "Storing forecast results",
        team_id=inputs.team_id,
        alert_id=inputs.alert_id,
        forecast_count=len(inputs.forecasts),
    )

    @sync_to_async
    def store_forecasts():
        with transaction.atomic():
            alert = AlertConfiguration.objects.get(id=inputs.alert_id)

            ForecastResult.objects.filter(alert_configuration=alert).delete()

            created_count = 0
            for forecast in inputs.forecasts:
                ForecastResult.objects.create(
                    team_id=inputs.team_id,
                    alert_configuration=alert,
                    series_index=forecast["series_index"],
                    breakdown_value=forecast.get("breakdown_value"),
                    forecast_timestamp=datetime.fromisoformat(forecast["forecast_timestamp"]),
                    predicted_value=forecast["predicted_value"],
                    lower_bound=forecast["lower_bound"],
                    upper_bound=forecast["upper_bound"],
                    confidence_level=forecast["confidence_level"],
                    historical_data_hash=forecast["historical_data_hash"],
                )
                created_count += 1

            return created_count

    count = await store_forecasts()

    logger.info(
        "Forecast results stored",
        stored_count=count,
    )

    return count


@temporalio.activity.defn
async def backfill_forecasts_activity(inputs: BackfillForecastInputs) -> dict:
    """
    Generate backfill forecasts for historical data points.

    For each historical point (starting from min_context), generates a forecast
    using only the data available at that time, then compares against the actual value.
    """
    from django.db import transaction

    from asgiref.sync import sync_to_async

    from posthog.schema import AlertState

    from posthog.models.alert import AlertCheck, AlertConfiguration, ForecastResult
    from posthog.temporal.forecast.chronos_service import ChronosForecaster

    logger.info(
        "Starting backfill forecasts",
        alert_id=inputs.alert_id,
        series_index=inputs.series_index,
        total_points=len(inputs.historical_values),
        max_forecasts=inputs.max_forecasts,
        min_context=inputs.min_context,
    )

    # Determine which indices to generate forecasts for (most recent first)
    available_indices = list(range(inputs.min_context, len(inputs.historical_values)))
    total_available = len(available_indices)

    if total_available <= inputs.max_forecasts:
        selected_indices = available_indices
    else:
        selected_indices = available_indices[-inputs.max_forecasts :]

    forecasts_created = 0
    checks_created = 0

    @sync_to_async
    def delete_existing_backfill_data(alert_id: str):
        alert = AlertConfiguration.objects.get(id=alert_id)
        deleted_checks, _ = AlertCheck.objects.filter(alert_configuration=alert, is_backfill=True).delete()
        deleted_forecasts, _ = ForecastResult.objects.filter(alert_configuration=alert).delete()
        return alert, deleted_checks, deleted_forecasts

    alert, deleted_checks, deleted_forecasts = await delete_existing_backfill_data(inputs.alert_id)

    if deleted_checks > 0 or deleted_forecasts > 0:
        logger.info(
            "Deleted existing backfill data",
            deleted_checks=deleted_checks,
            deleted_forecasts=deleted_forecasts,
        )

    for i in selected_indices:
        temporalio.activity.heartbeat()

        # Use only data up to (but not including) point i as context
        historical_context = inputs.historical_values[:i]

        # Apply lookback window
        if len(historical_context) > inputs.lookback_window:
            historical_context = historical_context[-inputs.lookback_window :]

        forecast_timestamp_str = inputs.timestamps[i]
        actual_value = inputs.historical_values[i]

        try:
            predicted, lower, upper = ChronosForecaster.forecast(
                historical_values=historical_context,
                prediction_length=1,
                confidence_level=inputs.confidence_level,
            )

            # Parse the timestamp
            if isinstance(forecast_timestamp_str, str):
                try:
                    ts = datetime.fromisoformat(forecast_timestamp_str.replace("Z", "+00:00"))
                except ValueError:
                    ts = datetime.strptime(forecast_timestamp_str, "%Y-%m-%d").replace(tzinfo=UTC)
            else:
                ts = forecast_timestamp_str

            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)

            @sync_to_async
            def store_backfill_result(
                alert_obj,
                team_id: int,
                series_index: int,
                breakdown_value: dict | None,
                timestamp: datetime,
                predicted_val: float,
                lower_val: float,
                upper_val: float,
                confidence: float,
                data_hash: str,
                actual_val: float,
            ):
                with transaction.atomic():
                    ForecastResult.objects.create(
                        team_id=team_id,
                        alert_configuration=alert_obj,
                        series_index=series_index,
                        breakdown_value=breakdown_value,
                        forecast_timestamp=timestamp,
                        predicted_value=predicted_val,
                        lower_bound=lower_val,
                        upper_bound=upper_val,
                        confidence_level=confidence,
                        historical_data_hash=data_hash,
                        model_version="chronos-bolt-tiny-backfill",
                    )

                    # Determine if this would have fired
                    breached = actual_val < lower_val or actual_val > upper_val
                    state = AlertState.FIRING if breached else AlertState.NOT_FIRING

                    AlertCheck.objects.create(
                        alert_configuration=alert_obj,
                        calculated_value=actual_val,
                        condition=alert_obj.condition,
                        targets_notified={},
                        state=state,
                        error=None,
                        is_backfill=True,
                    )

            await store_backfill_result(
                alert,
                inputs.team_id,
                inputs.series_index,
                inputs.breakdown_value,
                ts,
                predicted,
                lower,
                upper,
                inputs.confidence_level,
                ChronosForecaster.compute_data_hash(historical_context),
                actual_value,
            )

            forecasts_created += 1
            checks_created += 1

        except Exception as e:
            logger.warning(
                "Error generating backfill forecast",
                forecast_timestamp=forecast_timestamp_str,
                error=str(e),
            )
            continue

    logger.info(
        "Backfill forecasts completed",
        alert_id=inputs.alert_id,
        forecasts_created=forecasts_created,
        checks_created=checks_created,
    )

    return {
        "forecasts_created": forecasts_created,
        "checks_created": checks_created,
    }
