"""Scores points of a series against one-step forecasts from the AI gateway.

A scheduled check makes one gateway call per series and scores its latest point. A preview scores every
point with a rolling forecast, and sends all of its inputs through one batched client call. The checked
point is never part of its own history.
"""

import uuid
from collections.abc import Sequence
from typing import Any

import numpy as np
import structlog

from posthog.dataclasses import frozen
from posthog.llm.forecast_client import (
    ForecastError,
    ForecastNotConfiguredError,
    ForecastRejectedError,
    ForecastSeries,
    SeriesForecast,
    forecast,
)
from posthog.tasks.alerts.detector import FORECAST_DETECTOR_MAX_HISTORY, FORECAST_DETECTOR_MIN_HISTORY

from products.alerts.backend.forecast.access import forecast_detector_access_error
from products.alerts.backend.forecast.rules import (
    ForecastComparison,
    ForecastRule,
    QuantileLevels,
    compare,
    forecast_rule,
)
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

# Bounds the gateway work of one preview. The preview scores at most this many points, shared between
# its series, and the latest points of each series go first.
MAX_PREVIEW_POINTS = 500


@frozen
class _OwnerMessages:
    """What a person reads when the forecast cannot run. A check and a preview tell them different things."""

    paused_suffix: str
    refused: str
    rejected: str
    not_configured: str


_CHECK_MESSAGES = _OwnerMessages(
    paused_suffix=FORECAST_DETECTOR_PAUSED_SUFFIX,
    refused=FORECAST_DETECTOR_REFUSED_MESSAGE,
    rejected=FORECAST_DETECTOR_REJECTED_MESSAGE,
    not_configured=FORECAST_DETECTOR_NOT_CONFIGURED_MESSAGE,
)

_PREVIEW_MESSAGES = _OwnerMessages(
    paused_suffix="",
    refused="The forecast service is not accepting previews for this project.",
    rejected="The forecast service refused this preview. Try it again, and contact support if this keeps happening.",
    not_configured="Forecasts are not available on this PostHog deployment. Use a statistical detector instead.",
)


@frozen
class RollingForecast:
    """The forecast of every point a preview scored, for each series in the order they were given."""

    levels: QuantileLevels
    # One entry per point of each series. None is a point that was not scored: it has too little history,
    # or it is older than the points the preview has room for.
    comparisons: tuple[tuple[ForecastComparison | None, ...], ...]


def _rule(config: dict[str, Any]) -> ForecastRule:
    try:
        return forecast_rule(config)
    except ValueError as error:
        raise ForecastDetectorMisconfiguredError(str(error)) from error


def _forecast(
    series: Sequence[ForecastSeries],
    levels: QuantileLevels,
    *,
    attribution: JudgeAttribution,
    messages: _OwnerMessages,
) -> dict[str, SeriesForecast]:
    """Ask the gateway for each series' forecast. A forecast that fails raises an ``LLMDetectorError``
    subclass, never an empty result."""
    # Checked on every call, so withdrawing the rollout or AI data processing approval stops the calls.
    access_error = forecast_detector_access_error(
        distinct_id=str(attribution.user.distinct_id), organization=attribution.team.organization
    )
    if access_error:
        raise ForecastDetectorPausedError(f"{access_error} {messages.paused_suffix}".strip())

    from ee.hogai.utils.feature_flags import is_privacy_mode_enabled  # noqa: PLC0415

    try:
        return forecast(
            series,
            quantile_levels=levels.as_list(),
            ai_product=FORECAST_DETECTOR_AI_PRODUCT,
            team_id=attribution.team.id,
            trace_id=f"alert-forecast-detector-{uuid.uuid4()}",
            privacy_mode=is_privacy_mode_enabled(attribution.team),
        )
    except ForecastNotConfiguredError as error:
        raise ForecastDetectorNotConfiguredError(messages.not_configured) from error
    except ForecastRejectedError as error:
        if error.status_code in _PROJECT_REFUSED_STATUSES:
            raise ForecastDetectorPausedError(messages.refused) from error
        raise ForecastDetectorRejectedError(messages.rejected) from error
    except ForecastError as error:
        # Unreachable, timed out, failed on its side, or answered with a body the client could not
        # read. The raw message stays internal: the check records the class's owner message.
        raise ForecastDetectorUnavailableError(str(error)) from error


def _compare_point(
    rule: ForecastRule, levels: QuantileLevels, prediction: SeriesForecast, actual: float
) -> ForecastComparison:
    quantiles = prediction.quantiles
    return compare(
        rule,
        expected=quantiles[levels.expected][0],
        lower=quantiles[levels.lower][0],
        upper=quantiles[levels.upper][0],
        actual=actual,
    )


def _history_before(data: np.ndarray, index: int) -> np.ndarray:
    return data[:index][-FORECAST_DETECTOR_MAX_HISTORY:]


def score_latest(
    data: np.ndarray, config: dict[str, Any], *, attribution: JudgeAttribution
) -> ForecastComparison | None:
    """Compare the latest point with its forecast from the points before it.

    Returns None when the history is too short to forecast from, in which case no call was made.
    A forecast that fails raises an ``LLMDetectorError`` subclass. It never reports "no anomaly".
    """
    rule = _rule(config)
    history = _history_before(data, len(data) - 1)
    if len(history) < FORECAST_DETECTOR_MIN_HISTORY:
        return None

    levels = rule.quantile_levels
    forecasts = _forecast(
        [ForecastSeries(item_id="series", target=[float(value) for value in history])],
        levels,
        attribution=attribution,
        messages=_CHECK_MESSAGES,
    )
    comparison = _compare_point(rule, levels, forecasts["series"], float(data[-1]))
    logger.info(
        "alerts.forecast_detector.compared",
        fires=comparison.fires,
        side=comparison.side,
        history_points=len(history),
    )
    return comparison


def score_every_point(
    series: Sequence[np.ndarray], config: dict[str, Any], *, attribution: JudgeAttribution
) -> RollingForecast:
    """Compare each point of each series with a one-step forecast from only the points before it.

    A point with fewer than ``FORECAST_DETECTOR_MIN_HISTORY`` points before it is not scored. When the
    series hold more points than ``MAX_PREVIEW_POINTS``, each series scores its latest points up to an
    equal share. Makes no call when no point can be scored.
    """
    rule = _rule(config)
    levels = rule.quantile_levels
    points_per_series = max(MAX_PREVIEW_POINTS // max(len(series), 1), 1)

    inputs: list[ForecastSeries] = []
    for series_index, data in enumerate(series):
        first_scored = max(FORECAST_DETECTOR_MIN_HISTORY, len(data) - points_per_series)
        inputs.extend(
            ForecastSeries(
                item_id=f"{series_index}:{point_index}",
                target=[float(value) for value in _history_before(data, point_index)],
            )
            for point_index in range(first_scored, len(data))
        )

    forecasts = _forecast(inputs, levels, attribution=attribution, messages=_PREVIEW_MESSAGES) if inputs else {}
    comparisons = tuple(
        tuple(
            _compare_point(rule, levels, prediction, float(value))
            if (prediction := forecasts.get(f"{series_index}:{point_index}")) is not None
            else None
            for point_index, value in enumerate(data)
        )
        for series_index, data in enumerate(series)
    )
    logger.info(
        "alerts.forecast_detector.previewed",
        series=len(series),
        scored_points=len(inputs),
        fired_points=sum(1 for points in comparisons for comparison in points if comparison and comparison.fires),
    )
    return RollingForecast(levels=levels, comparisons=comparisons)
