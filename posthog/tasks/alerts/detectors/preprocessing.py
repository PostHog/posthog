from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from typing import Any

import numpy as np


def preprocess_data(data: np.ndarray, config: dict[str, Any] | None) -> np.ndarray:
    """
    Apply preprocessing transformations to time series data.

    Args:
        data: Input time series as numpy array
        config: Preprocessing configuration with optional keys:
            - diffs_n: int - Number of differencing passes (0 = raw, 1 = first-order)
            - lags_n: int - Number of lag features (0-10) for multivariate models
            - smooth_n: int - Moving average window size (0 or None = no smoothing)

    Returns:
        Preprocessed data as numpy array
    """
    if config is None:
        return data

    result = data.copy().astype(float)

    # 1. Apply moving average smoothing first (before diffs to smooth noise)
    smoothing_window = config.get("smooth_n", 0) or 0
    if smoothing_window > 0:
        result = moving_average(result, smoothing_window)

    # 2. Apply first difference (velocity)
    if config.get("diffs_n", 0):
        result = first_difference(result)

    # 3. Create lag features for multivariate detectors
    n_lags = config.get("lags_n", 0) or 0
    if n_lags > 0:
        result = create_lag_features(result, n_lags)

    return result


def _parse_timestamp(timestamp: str | None) -> datetime | None:
    if not isinstance(timestamp, str):
        return None
    try:
        return datetime.fromisoformat(timestamp)
    except ValueError:
        return None


def deseasonalize(
    data: np.ndarray,
    timestamps: Sequence[str | None],
    *,
    min_bucket_samples: int = 2,
) -> np.ndarray:
    """Subtract a day-of-week and hour-of-day baseline from a time series.

    Each point is grouped by its (weekday, hour) bucket, and that bucket's median level is
    subtracted from it. A point is then scored against the same hour on the same weekday
    rather than against the raw level, so a normal weekly cycle - quiet weekends, busy
    weekday mornings - no longer reads as a level shift while a genuine spike still stands out.

    Daily points all share hour 0, so the bucket reduces to the weekday alone.

    A bucket with fewer than ``min_bucket_samples`` points falls back to the global median, so
    a sparse bucket cannot zero out a real spike. If timestamps are missing, mismatched, or
    unparseable, the data is returned unchanged so detection still runs.
    """
    values = data.astype(float)
    if len(values) != len(timestamps):
        return values

    keyed: list[tuple[tuple[int, int], float]] = []
    buckets: dict[tuple[int, int], list[float]] = defaultdict(list)
    for timestamp, value in zip(timestamps, values):
        moment = _parse_timestamp(timestamp)
        if moment is None:
            return values
        key = (moment.weekday(), moment.hour)
        keyed.append((key, value))
        buckets[key].append(value)

    global_baseline = float(np.median(values))
    baseline = {
        key: (float(np.median(bucket_values)) if len(bucket_values) >= min_bucket_samples else global_baseline)
        for key, bucket_values in buckets.items()
    }

    return np.array([value - baseline[key] for key, value in keyed], dtype=float)


def first_difference(data: np.ndarray) -> np.ndarray:
    """
    Compute first difference of time series.
    Prepends first value to maintain length.
    """
    diff = np.diff(data, prepend=data[0])
    return diff


def moving_average(data: np.ndarray, window: int) -> np.ndarray:
    """
    Simple moving average smoothing.

    Trailing (causal) window: index i averages data[i - window + 1 : i + 1], padding
    only on the left. A centered window would average the most recent point against
    padding replicated from itself, then need `window - 1` more real points to arrive
    before that point's smoothed value stabilizes - each new point silently changes
    the smoothed value of points already reported, and shifts an anomaly's peak score
    onto a later, unrelated point instead of the one where the deviation happened.
    """
    if len(data) < window:
        return data

    kernel = np.ones(window) / window
    padded = np.pad(data, (window - 1, 0), mode="edge")
    smoothed = np.convolve(padded, kernel, mode="valid")
    return smoothed


def exponential_smoothing(data: np.ndarray, alpha: float = 0.3) -> np.ndarray:
    """
    Exponential moving average smoothing.

    Args:
        data: Input time series
        alpha: Smoothing factor (0 < alpha <= 1). Higher = less smoothing.
    """
    result = np.zeros_like(data, dtype=float)
    result[0] = data[0]
    for i in range(1, len(data)):
        result[i] = alpha * data[i] + (1 - alpha) * result[i - 1]
    return result


def create_lag_features(data: np.ndarray, n_lags: int) -> np.ndarray:
    """
    Create lagged features for multivariate detection.

    For a 1D array, creates a 2D array where each row contains
    [current_value, lag_1, lag_2, ..., lag_n].

    Args:
        data: 1D input time series
        n_lags: Number of lag features to create (1-10)

    Returns:
        2D array of shape (n_samples, n_lags + 1)
    """
    n_lags = min(max(n_lags, 0), 10)  # Limit to 0-10 lags
    if n_lags == 0:
        return data

    n_samples = len(data)
    features = np.zeros((n_samples, n_lags + 1))

    # First column is current value
    features[:, 0] = data

    # Add lag features
    for lag in range(1, n_lags + 1):
        # Shift and fill beginning with first value
        lagged = np.roll(data, lag)
        lagged[:lag] = data[0]
        features[:, lag] = lagged

    return features
