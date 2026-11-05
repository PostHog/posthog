import math

Z_95 = 1.96


def wilson_interval(successes: int, total: int, z: float = Z_95) -> tuple[float, float]:
    """95% Wilson score interval for a proportion. It stays inside [0, 1] and is sane at 0 or n successes,
    which matters here because failure counts are small."""
    if total <= 0:
        return 0.0, 1.0
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - margin), min(1.0, centre + margin)
