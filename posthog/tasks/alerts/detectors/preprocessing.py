from typing import Any

import numpy as np


def preprocess_data(data: np.ndarray, config: dict[str, Any] | None) -> np.ndarray:
    """
    Apply preprocessing transformations to time series data.

    Args:
        data: Input time series as numpy array
        config: Preprocessing configuration with optional keys:
            - diffs: bool - Apply first difference
            - lags: int - Number of lag features (0-10) for multivariate models
            - smoothing: int - Moving average window size (0 or None = no smoothing)

    Returns:
        Preprocessed data as numpy array
    """
    if config is None:
        return data

    result = data.copy().astype(float)

    # 1. Apply moving average smoothing first (before diffs to smooth noise)
    smoothing_window = config.get("smoothing", 0) or 0
    if smoothing_window > 0:
        result = moving_average(result, smoothing_window)

    # 2. Apply first difference (velocity)
    if config.get("diffs", False):
        result = first_difference(result)

    # 3. Create lag features for multivariate detectors
    n_lags = config.get("lags", 0) or 0
    if n_lags > 0:
        result = create_lag_features(result, n_lags)

    return result


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
