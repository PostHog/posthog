import datetime

import pytest

import numpy as np
from parameterized import parameterized

from posthog.schema import IntervalType

from products.alerts.backend.forecasting.engine import ForecastResult, get_forecast_engine


def _daily_dates(n: int) -> list[str]:
    start = datetime.date(2026, 1, 1)
    return [(start + datetime.timedelta(days=i)).isoformat() for i in range(n)]


class TestProphetEngine:
    def test_registry_returns_prophet_engine(self):
        engine = get_forecast_engine({"type": "ForecastConfig", "engine": "prophet"})
        assert engine is not None

    def test_registry_rejects_unknown_engine(self):
        with pytest.raises(ValueError):
            get_forecast_engine({"type": "ForecastConfig", "engine": "nonsense"})

    def test_forecast_shape(self):
        np.random.seed(42)  # Prophet's uncertainty sampling uses the global numpy RNG
        engine = get_forecast_engine({"engine": "prophet"})
        values = [float(100 + 2 * i) for i in range(60)]
        result = engine.forecast(_daily_dates(60), values, horizon=7, interval_width=0.95, interval=IntervalType.DAY)
        assert isinstance(result, ForecastResult)
        assert len(result.dates) == len(result.yhat) == len(result.lower) == len(result.upper) == 7
        assert result.dates[0].startswith("2026-03-02")  # day after the last input date

    @parameterized.expand(
        [
            ("upward_trend", [float(100 + 2 * i) for i in range(60)], lambda fc: fc.yhat[-1] > 210),
            ("flat", [100.0] * 60, lambda fc: abs(fc.yhat[-1] - 100.0) < 10),
        ]
    )
    def test_forecast_follows_trend(self, _name, values, check):
        np.random.seed(42)
        engine = get_forecast_engine({"engine": "prophet"})
        result = engine.forecast(_daily_dates(60), values, horizon=7, interval_width=0.95, interval=IntervalType.DAY)
        assert check(result)

    def test_band_contains_point_forecast(self):
        np.random.seed(42)
        engine = get_forecast_engine({"engine": "prophet"})
        values = [float(100 + 2 * i + (5 if i % 7 == 0 else 0)) for i in range(60)]
        result = engine.forecast(_daily_dates(60), values, horizon=7, interval_width=0.95, interval=IntervalType.DAY)
        for i in range(7):
            assert result.lower[i] <= result.yhat[i] <= result.upper[i]

    def test_fit_quality_and_components_populated(self):
        np.random.seed(42)
        engine = get_forecast_engine({"engine": "prophet"})
        # Tiny alternating jitter avoids a perfectly noiseless line, where Prophet's MAP-estimated
        # observation noise collapses far below its own optimizer convergence residual, making the
        # uncertainty band pathologically narrower than the fit itself and starving fit_coverage.
        values = [float(100 + 2 * i + (-1) ** i * 0.3) for i in range(60)]
        result = engine.forecast(_daily_dates(60), values, horizon=7, interval_width=0.95, interval=IntervalType.DAY)
        assert result.fit_mape is not None and result.fit_mape < 0.1  # near-perfect fit on a clean line
        assert result.fit_coverage is not None and result.fit_coverage > 0.8
        assert result.components is not None
        assert len(result.components["trend"]) == 7
