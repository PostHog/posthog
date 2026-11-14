"""Scores the latest point of a series against a one-step forecast from the AI gateway.

One gateway call per series. The checked point is never part of its own history.
"""

import uuid
from typing import Any

import numpy as np
import structlog

from posthog.llm.forecast_client import (
    ForecastError,
    ForecastNotConfiguredError,
    ForecastRejectedError,
    ForecastSeries,
    forecast,
)
from posthog.tasks.alerts.detector import FORECAST_DETECTOR_MAX_HISTORY, FORECAST_DETECTOR_MIN_HISTORY

from products.alerts.backend.forecast.access import forecast_detector_access_error
from products.alerts.backend.forecast.rules import ForecastComparison, compare, forecast_rule
from products.alerts.backend.judge.contract import (
    ForecastDetectorMisconfiguredError,
    ForecastDetectorNotConfiguredError,
    ForecastDetectorPausedError,
    ForecastDetectorRejectedError,
    ForecastDetectorUnavailableError,
    JudgeAttribution,
)

logger = structlog.get_logger(__name__)

# Own product key on the gateway's events, so the forecast detector's calls are separable from other callers.
FORECAST_DETECTOR_AI_PRODUCT = "alerts_forecast_detector"

FORECAST_DETECTOR_PAUSED_SUFFIX = (
    "This alert is still on and starts checking again once that changes. To keep it running now, "
    "switch it to a statistical detector."
)

FORECAST_DETECTOR_REFUSED_MESSAGE = (
    f"The forecast service is not accepting checks for this project. {FORECAST_DETECTOR_PAUSED_SUFFIX}"
)

FORECAST_DETECTOR_REJECTED_MESSAGE = (
    "The forecast service refused this check. The alert is still on and the next check tries again. "
    "If this keeps happening, contact support."
)

FORECAST_DETECTOR_NOT_CONFIGURED_MESSAGE = (
    "Forecasts are not available on this PostHog deployment. The alert is still on. To keep it running now, "
    "switch it to a statistical detector."
)

# A 402 or 403 refuses the project, not this request, so the check pauses until that changes.
_PROJECT_REFUSED_STATUSES = frozenset({402, 403})


def score_latest(
    data: np.ndarray, config: dict[str, Any], *, attribution: JudgeAttribution
) -> ForecastComparison | None:
    """Compare the latest point with its forecast from the points before it.

    Returns None when the history is too short to forecast from, in which case no call was made.
    A forecast that fails raises an ``LLMDetectorError`` subclass. It never reports "no anomaly".
    """
    try:
        rule = forecast_rule(config)
    except ValueError as error:
        raise ForecastDetectorMisconfiguredError(str(error)) from error
    history = data[:-1][-FORECAST_DETECTOR_MAX_HISTORY:]
    if len(history) < FORECAST_DETECTOR_MIN_HISTORY:
        return None

    access_error = forecast_detector_access_error(
        distinct_id=str(attribution.user.distinct_id), organization_id=attribution.team.organization_id
    )
    if access_error:
        raise ForecastDetectorPausedError(f"{access_error} {FORECAST_DETECTOR_PAUSED_SUFFIX}")

    lower_level, expected_level, upper_level = rule.quantile_levels
    try:
        forecasts = forecast(
            [ForecastSeries(item_id="series", target=[float(value) for value in history])],
            quantile_levels=rule.quantile_levels,
            ai_product=FORECAST_DETECTOR_AI_PRODUCT,
            team_id=attribution.team.id,
            trace_id=f"alert-forecast-detector-{uuid.uuid4()}",
        )
    except ForecastNotConfiguredError as error:
        raise ForecastDetectorNotConfiguredError(FORECAST_DETECTOR_NOT_CONFIGURED_MESSAGE) from error
    except ForecastRejectedError as error:
        if error.status_code in _PROJECT_REFUSED_STATUSES:
            raise ForecastDetectorPausedError(FORECAST_DETECTOR_REFUSED_MESSAGE) from error
        raise ForecastDetectorRejectedError(FORECAST_DETECTOR_REJECTED_MESSAGE) from error
    except ForecastError as error:
        # Unreachable, timed out, failed on its side, or answered with a body the client could not
        # read. The raw message stays internal: the check records the class's owner message.
        raise ForecastDetectorUnavailableError(str(error)) from error

    quantiles = forecasts["series"].quantiles
    comparison = compare(
        rule,
        expected=quantiles[expected_level][0],
        lower=quantiles[lower_level][0],
        upper=quantiles[upper_level][0],
        actual=float(data[-1]),
    )
    logger.info(
        "alerts.forecast_detector.compared",
        fires=comparison.fires,
        mode=comparison.mode,
        history_points=len(history),
    )
    return comparison
