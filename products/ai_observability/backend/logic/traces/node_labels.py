from collections import Counter
from collections.abc import Sequence


def number_repeated_names(names: Sequence[str]) -> list[str]:
    """Labels names given in tree order. Two steps can share a name, such as two calls to the same model, so a
    repeated name gets its position among the names that match it."""
    totals = Counter(names)
    seen: Counter[str] = Counter()
    labels: list[str] = []
    for name in names:
        seen[name] += 1
        labels.append(f"{name} #{seen[name]}" if totals[name] > 1 else name)
    return labels
