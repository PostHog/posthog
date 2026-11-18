"""Calls the time-series forecast model that the Go ai-gateway serves on ``POST /v1/forecast``.

The model is zero-shot, so one request holds many series and there is no fit per series. ``forecast``
splits a large input into requests that stay inside the gateway's limits, and returns the quantiles
of each series by its ``item_id``.
"""

import math
from collections.abc import Mapping, Sequence

import httpx

from posthog.dataclasses import frozen
from posthog.llm.gateway_client import ai_gateway_headers, resolve_https_ai_gateway_config, team_distinct_id

FORECAST_MODEL = "posthog/mistralai/timestral-28m"

MAX_SERIES_PER_REQUEST = 1_000
MAX_TOKENS_PER_REQUEST = 4_096
# The gateway counts one token for each 32-step patch of one series, and pads every series to the
# longest one in the request.
PATCH_LENGTH = 32

QUANTILE_LEVELS = frozenset({0.01, *(round(step * 0.05, 2) for step in range(1, 20)), 0.99})

# The gateway waits up to 60 seconds for a cold model, so the read timeout must be longer than that.
DEFAULT_TIMEOUT = httpx.Timeout(75.0, connect=10.0)

MAX_ERROR_MESSAGE_CHARS = 300


class ForecastError(Exception):
    """A forecast call failed. ``retryable`` tells the caller whether the same call can succeed later."""

    retryable = False

    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class ForecastNotConfiguredError(ForecastError):
    """No AI gateway is configured, or its URL would send the key in clear, so no call was made."""


class ForecastUnavailableError(ForecastError):
    """The gateway was not reached, timed out, was busy, or failed on its side."""

    retryable = True


class ForecastRejectedError(ForecastError):
    """The gateway refused the request, for example as invalid or unauthorized."""


class ForecastResponseError(ForecastError):
    """The gateway answered with a body that does not match the forecast response.

    Retryable, because one unreadable body does not mean that the next call gets one too.
    """

    retryable = True


@frozen
class ForecastSeries:
    item_id: str
    # The history, oldest first. None is a missing value.
    target: Sequence[float | None]


@frozen
class SeriesForecast:
    # One value for each forecast step, by quantile level.
    quantiles: Mapping[float, tuple[float, ...]]


def forecast(
    series: Sequence[ForecastSeries],
    *,
    quantile_levels: Sequence[float],
    ai_product: str,
    team_id: int,
    prediction_length: int = 1,
    trace_id: str | None = None,
    timeout: httpx.Timeout | float = DEFAULT_TIMEOUT,
    privacy_mode: bool = False,
) -> dict[str, SeriesForecast]:
    """Forecast ``prediction_length`` steps of each series, keyed by ``item_id``.

    ``ai_product`` and ``team_id`` label the gateway's event, and ``team_id`` names the team the call is for.
    With ``privacy_mode``, the gateway's event keeps no inputs or outputs.
    Raises ``ValueError`` for an input the gateway cannot accept, and a ``ForecastError`` subclass when the call fails.
    """
    _validate(
        series,
        quantile_levels=quantile_levels,
        ai_product=ai_product,
        team_id=team_id,
        prediction_length=prediction_length,
    )
    if not series:
        return {}
    gateway = resolve_https_ai_gateway_config()
    if gateway is None:
        raise ForecastNotConfiguredError("Forecasts need AI_GATEWAY_URL (https) and AI_GATEWAY_API_KEY")

    headers = {
        **(
            ai_gateway_headers(
                ai_product=ai_product,
                trace_id=trace_id,
                properties={"team_id": str(team_id)},
                distinct_id=team_distinct_id(team_id),
            )
            or {}
        ),
        "Authorization": f"Bearer {gateway.api_key}",
        **({"X-PostHog-Privacy-Mode": "true"} if privacy_mode else {}),
    }
    url = gateway.url.rstrip("/") + "/forecast"
    forecasts: dict[str, SeriesForecast] = {}
    with httpx.Client(trust_env=False, timeout=timeout) as client:
        for batch in split_into_requests(series, prediction_length):
            body = {
                "model": FORECAST_MODEL,
                "inputs": [{"item_id": item.item_id, "target": _json_target(item.target)} for item in batch],
                "parameters": {"prediction_length": prediction_length, "quantile_levels": list(quantile_levels)},
            }
            try:
                response = client.post(url, json=body, headers=headers)
            except httpx.HTTPError as exc:
                raise ForecastUnavailableError(f"The AI gateway was not reached: {exc.__class__.__name__}") from exc
            forecasts.update(
                _parse_response(
                    response,
                    item_ids=[item.item_id for item in batch],
                    quantile_levels=quantile_levels,
                    prediction_length=prediction_length,
                )
            )
    return forecasts


def split_into_requests(series: Sequence[ForecastSeries], prediction_length: int) -> list[list[ForecastSeries]]:
    """Group the series into requests that each stay inside the gateway's series and token limits.

    Series of similar length share a request, so less of each request is padding.
    """
    requests: list[list[ForecastSeries]] = []
    current: list[ForecastSeries] = []
    for item in sorted(series, key=lambda item: len(item.target)):
        # Sorted by length, so this series is the longest one in the current request.
        tokens = (len(current) + 1) * _tokens_per_series(len(item.target), prediction_length)
        if current and (len(current) == MAX_SERIES_PER_REQUEST or tokens > MAX_TOKENS_PER_REQUEST):
            requests.append(current)
            current = []
        current.append(item)
    if current:
        requests.append(current)
    return requests


def _tokens_per_series(history_length: int, prediction_length: int) -> int:
    return math.ceil(history_length / PATCH_LENGTH) + math.ceil(prediction_length / PATCH_LENGTH)


def _validate(
    series: Sequence[ForecastSeries],
    *,
    quantile_levels: Sequence[float],
    ai_product: str,
    team_id: int,
    prediction_length: int,
) -> None:
    if not ai_product:
        raise ValueError("ai_product is required")
    if team_id <= 0:
        raise ValueError(f"team_id must be positive, got {team_id}")
    if prediction_length < 1:
        raise ValueError(f"prediction_length must be at least 1, got {prediction_length}")
    if not quantile_levels:
        raise ValueError("At least one quantile level is required")
    unknown_levels = sorted(set(quantile_levels) - QUANTILE_LEVELS)
    if unknown_levels:
        raise ValueError(f"The gateway does not serve the quantile levels {unknown_levels}")
    if len({item.item_id for item in series}) != len(series):
        raise ValueError("Each series needs a different item_id")
    for item in series:
        if not item.target:
            raise ValueError(f"Series {item.item_id!r} has no history")
        if _tokens_per_series(len(item.target), prediction_length) > MAX_TOKENS_PER_REQUEST:
            raise ValueError(f"Series {item.item_id!r} is longer than one forecast request can hold")


def _json_target(target: Sequence[float | None]) -> list[float | None]:
    # JSON has no NaN or infinity, and the gateway reads null as a missing value.
    return [float(value) if value is not None and math.isfinite(value) else None for value in target]


def _parse_response(
    response: httpx.Response,
    *,
    item_ids: Sequence[str],
    quantile_levels: Sequence[float],
    prediction_length: int,
) -> dict[str, SeriesForecast]:
    status = response.status_code
    if status in (408, 429) or status >= 500:
        raise ForecastUnavailableError(f"The AI gateway returned HTTP {status}", status_code=status)
    if status != 200:
        raise ForecastRejectedError(
            f"The AI gateway refused the forecast request with HTTP {status}{_gateway_error_suffix(response)}",
            status_code=status,
        )
    try:
        payload: object = response.json()
    except ValueError as exc:
        raise ForecastResponseError("The AI gateway returned a non-JSON forecast body") from exc
    predictions = payload.get("predictions") if isinstance(payload, dict) else None
    if not isinstance(predictions, list):
        raise ForecastResponseError("The forecast response has no predictions list")

    by_item_id = {
        prediction["item_id"]: prediction
        for prediction in predictions
        if isinstance(prediction, dict) and isinstance(prediction.get("item_id"), str)
    }
    forecasts: dict[str, SeriesForecast] = {}
    for item_id in item_ids:
        prediction = by_item_id.get(item_id)
        if prediction is None:
            raise ForecastResponseError(f"The forecast response has no prediction for series {item_id!r}")
        # The gateway names each quantile by its level as a string, for example "0.5" or "0.05".
        values_by_level = {_as_level(key): values for key, values in prediction.items()}
        forecasts[item_id] = SeriesForecast(
            quantiles={
                level: _quantile_values(
                    values_by_level.get(level), item_id=item_id, level=level, prediction_length=prediction_length
                )
                for level in quantile_levels
            }
        )
    return forecasts


def _quantile_values(values: object, *, item_id: str, level: float, prediction_length: int) -> tuple[float, ...]:
    if (
        not isinstance(values, list)
        or len(values) != prediction_length
        or not all(
            isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value) for value in values
        )
    ):
        raise ForecastResponseError(f"The forecast for series {item_id!r} has no readable {level} quantile")
    return tuple(float(value) for value in values)


def _as_level(key: str) -> float | None:
    try:
        return round(float(key), 2)
    except ValueError:
        return None


def _gateway_error_suffix(response: httpx.Response) -> str:
    try:
        error = response.json().get("error")
    except (ValueError, AttributeError):
        return ""
    message = error.get("message") if isinstance(error, dict) else None
    if not isinstance(message, str) or not message:
        return ""
    return f": {message[:MAX_ERROR_MESSAGE_CHARS]}"
