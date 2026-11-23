"""Order measures and proposals by what a missing shared definition costs.

The cost grows with the people who build or view a number, and with how hard the number is to compute the
same way twice. Complexity alone put a query that one person wrote above one that a whole team reads.
"""

import math

from .query_complexity import Complexity

_COMPLEXITY_WEIGHTS = {Complexity.UNKNOWN: 1, Complexity.LOW: 1, Complexity.MEDIUM: 2, Complexity.HIGH: 4}


def priority(*, complexity: int, reach: int, measures: int = 1) -> float:
    """The rank score of one measure or proposal. A higher score ranks first.

    ``reach`` counts the people who built or viewed the number. Its log keeps one widely viewed chart from
    outranking every other row. Each extra way of writing the same number adds half its weight, because
    definitions that drift apart are what a catalog fixes."""
    weight = _COMPLEXITY_WEIGHTS.get(Complexity(complexity), 1)
    return round(math.log2(1 + reach) * weight * (1 + 0.5 * max(0, measures - 1)), 4)
