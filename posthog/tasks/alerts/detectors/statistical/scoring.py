import math

from scipy.special import erf

# A standard normal has its third quartile at 0.6745 sigma and an interquartile
# range of 1.349 sigma. Both convert an IQR fence distance into sigma units.
NORMAL_Q3_IN_SIGMA = 0.6745
NORMAL_IQR_IN_SIGMA = 1.349


def deviation_to_probability(deviation_in_sigma: float, window_size: int) -> float:
    """Probability that a window of ``window_size`` normal draws holds no deviation this large.

    Scaling instead against the window's own deviations (min-max, or standardizing
    against them) gives the window's largest point a score of 1.0 whatever its
    margin, so the score reports rank and every new window record fires.
    """
    if not math.isfinite(deviation_in_sigma):
        return 1.0
    point_probability = float(erf(abs(deviation_in_sigma) / math.sqrt(2)))
    return min(1.0, max(0.0, point_probability ** max(window_size, 1)))
