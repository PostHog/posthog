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


def preprocessing_alters_scored_value(config: dict[str, Any] | None) -> bool:
    """True if preprocessing makes the scored signal differ from the raw value.

    Smoothing and differencing both transform what the detector scores away from the raw
    value the user is shown. When that happens, a point can score as anomalous on the
    transformed signal while its raw value is unremarkable, so the fired value and the
    scored signal disagree. Detectors use this to decide whether the raw-band guard applies.
    """
    if not config:
        return False
    return bool((config.get("smooth_n", 0) or 0) > 0 or (config.get("diffs_n", 0) or 0) > 0)


def within_normal_band(window: np.ndarray, value: float, n_sigma: float) -> bool:
    """Whether ``value`` sits within ``n_sigma`` standard deviations of the window mean.

    Used to reconcile a transformed-signal anomaly with the raw value: a point squarely
    inside the raw series' normal range (e.g. a return to baseline after a spike) is not
    itself anomalous, even if the smoothed first difference trips the score.
    """
    if len(window) == 0:
        return False
    mean = float(np.mean(window))
    std = float(np.std(window))
    if std == 0:
        return value == mean
    return abs(value - mean) <= n_sigma * std


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
    Uses 'same' mode to preserve array length.
    """
    if len(data) < window:
        return data

    kernel = np.ones(window) / window
    # Use 'same' mode but handle edges by padding
    padded = np.pad(data, (window // 2, window - 1 - window // 2), mode="edge")
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
