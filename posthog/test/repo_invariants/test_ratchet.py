import warnings
from datetime import date

import pytest
import time_machine

from posthog.test.repo_invariants.ratchet import RatchetGraceWarning, enforce_baseline

BLOCKING_FROM = date(2026, 10, 20)


@pytest.mark.parametrize(
    ("today", "added", "removed", "expected"),
    [
        ("2026-10-19", ["new"], [], "warns"),
        ("2026-10-20", ["new"], [], "fails"),
        ("2026-10-19", ["new"], ["fixed"], "fails"),
    ],
)
def test_grace_period_boundary(today: str, added: list[str], removed: list[str], expected: str) -> None:
    with time_machine.travel(date.fromisoformat(today), tick=False), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        if expected == "fails":
            with pytest.raises(AssertionError, match="baseline mismatch"):
                enforce_baseline(added=added, removed=removed, blocking_from=BLOCKING_FROM, message="baseline mismatch")
        else:
            enforce_baseline(added=added, removed=removed, blocking_from=BLOCKING_FROM, message="baseline mismatch")
    assert [w.category for w in caught] == ([RatchetGraceWarning] if expected == "warns" else [])


def test_a_grace_period_longer_than_the_cap_is_refused() -> None:
    with time_machine.travel(date(2026, 10, 1), tick=False):
        with pytest.raises(ValueError):
            enforce_baseline(added=["new"], removed=[], blocking_from=BLOCKING_FROM, message="baseline mismatch")
