import numpy as np
from scipy.special import erf

# A standard normal has its third quartile at 0.6745 sigma and an interquartile
# range of 1.349 sigma. Both convert an IQR fence distance into sigma units.
NORMAL_Q3_IN_SIGMA = 0.6745
NORMAL_IQR_IN_SIGMA = 1.349


def deviation_to_probability(deviation_in_sigma: float, window_size: int) -> float:
    """Score how extreme a deviation is, on a scale the training window cannot move.

    A deviation is scored against the normal distribution, then corrected for the
    number of points the window holds: the result is the probability that a window
    of ``window_size`` normal draws contains no deviation this large. A score of
    0.95 therefore means a deviation this large appears in a window of this length
    only 5% of the time by chance.

    The scale depends on the detector config and never on the window's own values.
    A normalization that rescales against the window (min-max, or standardizing
    against the window's own deviations) makes the largest point in the window
    score 1.0 whatever its margin, so every new window record fires and the score
    reports rank instead of extremity.
    """
    if not np.isfinite(deviation_in_sigma):
        return 1.0
    point_probability = float(erf(abs(deviation_in_sigma) / np.sqrt(2)))
    return float(np.clip(point_probability ** max(window_size, 1), 0.0, 1.0))
