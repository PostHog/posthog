import hashlib
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import structlog

logger = structlog.get_logger(__name__)

if TYPE_CHECKING:
    pass


class ChronosForecaster:
    """
    Wrapper for Chronos-Bolt time series forecasting model.
    Uses lazy loading to avoid memory overhead at worker startup.
    """

    _model = None
    _model_name = "amazon/chronos-bolt-tiny"

    @classmethod
    def get_model(cls):
        if cls._model is None:
            try:
                import torch
                from chronos import BaseChronosPipeline

                logger.info("Loading Chronos model", model_name=cls._model_name)
                cls._model = BaseChronosPipeline.from_pretrained(
                    cls._model_name,
                    device_map="cpu",
                    dtype=torch.float32,
                )
                logger.info("Chronos model loaded successfully")
            except ImportError as e:
                logger.exception("Failed to import Chronos dependencies")
                raise ImportError(
                    "Chronos forecasting requires the 'chronos-forecasting' and 'torch' packages. "
                    "Install them with: pip install 'posthog[forecast]'"
                ) from e
        return cls._model

    @classmethod
    def forecast(
        cls,
        historical_values: list[float],
        prediction_length: int = 1,
        confidence_level: float = 0.95,
    ) -> tuple[float, float, float]:
        """
        Generate probabilistic forecast for time series data.

        Args:
            historical_values: Historical time series values
            prediction_length: Number of future points to predict
            confidence_level: Confidence level for prediction interval (0-1)

        Returns:
            Tuple of (predicted_value, lower_bound, upper_bound)
        """
        import torch

        model = cls.get_model()
        context = torch.tensor(historical_values, dtype=torch.float32).unsqueeze(0)

        # Map confidence level to closest available quantiles
        # Bolt models support: [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
        alpha = 1 - confidence_level
        lower_q = max(0.1, alpha / 2)
        upper_q = min(0.9, 1 - alpha / 2)

        quantiles_result, _ = model.predict_quantiles(
            context,
            prediction_length=prediction_length,
            quantile_levels=[lower_q, 0.5, upper_q],
        )

        # Shape is [batch, prediction_length, num_quantiles]
        # Get the last prediction step
        lower = float(quantiles_result[0, -1, 0].item())
        predicted = float(quantiles_result[0, -1, 1].item())
        upper = float(quantiles_result[0, -1, 2].item())

        return predicted, lower, upper

    @classmethod
    def forecast_batch(
        cls,
        historical_series: list[list[float]],
        prediction_length: int = 1,
        confidence_level: float = 0.95,
    ) -> list[tuple[float, float, float]]:
        """
        Generate probabilistic forecasts for multiple time series in batch.

        Args:
            historical_series: List of historical time series
            prediction_length: Number of future points to predict
            confidence_level: Confidence level for prediction interval

        Returns:
            List of (predicted_value, lower_bound, upper_bound) tuples
        """
        import torch

        model = cls.get_model()

        max_len = max(len(s) for s in historical_series)
        padded = []
        for series in historical_series:
            padding = [0.0] * (max_len - len(series))
            padded.append(padding + series)

        context = torch.tensor(padded, dtype=torch.float32)

        # Map confidence level to closest available quantiles
        alpha = 1 - confidence_level
        lower_q = max(0.1, alpha / 2)
        upper_q = min(0.9, 1 - alpha / 2)

        quantiles_result, _ = model.predict_quantiles(
            context,
            prediction_length=prediction_length,
            quantile_levels=[lower_q, 0.5, upper_q],
        )

        # Shape is [batch, prediction_length, num_quantiles]
        results = []
        for i in range(len(historical_series)):
            lower = float(quantiles_result[i, -1, 0].item())
            predicted = float(quantiles_result[i, -1, 1].item())
            upper = float(quantiles_result[i, -1, 2].item())
            results.append((predicted, lower, upper))

        return results

    @staticmethod
    def compute_data_hash(values: list[float]) -> str:
        """Compute a hash of the historical data for cache invalidation."""
        data_str = ",".join(f"{v:.6f}" for v in values)
        return hashlib.sha256(data_str.encode()).hexdigest()[:16]

    @staticmethod
    def get_forecast_timestamp(interval: str) -> datetime:
        """
        Get the timestamp for the forecast based on the alert interval.
        Returns the next expected data point time.
        """
        now = datetime.now(UTC)
        if interval == "hourly":
            return now.replace(minute=0, second=0, microsecond=0)
        elif interval == "daily":
            return now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif interval == "weekly":
            days_until_monday = (7 - now.weekday()) % 7
            return (now + __import__("datetime").timedelta(days=days_until_monday)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
        else:
            return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
