from typing import Any

import numpy as np


def preprocess_data(data: np.ndarray, config: dict[str, Any] | None, preserve_scale: bool = False) -> np.ndarray:
    """
    Apply preprocessing transformations to time series data.

    Args:
        data: Input time series as numpy array
        config: Preprocessing configuration with optional keys:
            - diffs_n: int - Number of differencing passes (0 = raw, 1 = first-order)
            - lags_n: int - Number of lag features (0-10) for multivariate models
            - smooth_n: int - Smoothing strength (0 or None = no smoothing)
        preserve_scale: Keep the rectangular smoothing kernel even when differencing.
            The exponential kernel below roughly doubles the smoothed magnitude of a
            step. A normalized detector divides that gain out, but a detector that
            compares the result against absolute bounds does not, so it must keep the
            old kernel or a saved bound would silently change meaning.

    Returns:
        Preprocessed data as numpy array
    """
    if config is None:
        return data

    result = data.copy().astype(float)

    # 1. Smooth first, so the difference below measures a trend and not noise.
    smoothing_n = config.get("smooth_n", 0) or 0
    differencing = bool(config.get("diffs_n", 0))
    if smoothing_n > 0:
        if differencing and not preserve_scale:
            # A rectangular window and a first difference collapse into a lagged
            # difference: smoothed[i] - smoothed[i - 1] equals
            # (data[i] - data[i - smooth_n]) / smooth_n. Each step change thus enters the
            # differenced series twice - once when it happens, and again smooth_n points
            # later, when it leaves the window. The second entry flags a point that is
            # itself unremarkable. An exponential kernel decays instead of ending, so a
            # change contributes once and then fades.
            result = exponential_smoothing(result, alpha=2.0 / (smoothing_n + 1))
        else:
            result = moving_average(result, smoothing_n)

    # 2. Apply first difference (velocity)
    if differencing:
        result = first_difference(result)

    # 3. Create lag features for multivariate detectors
    n_lags = config.get("lags_n", 0) or 0
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
