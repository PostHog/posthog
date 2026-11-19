import math

from posthog.dataclasses import frozen

Z_95 = 1.96


@frozen
class Interval:
    low: float
    high: float


def wilson_interval(successes: float, total: int, z: float = Z_95) -> Interval:
    """95% Wilson score interval for a proportion. It stays inside [0, 1] and is sane at 0 or n successes,
    which matters here because failure counts are small."""
    if total <= 0:
        return Interval(low=0.0, high=1.0)
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return Interval(low=max(0.0, centre - margin), high=min(1.0, centre + margin))
