import warnings
from collections.abc import Sequence
from datetime import date, timedelta

MAX_GRACE = timedelta(days=14)


class RatchetGraceWarning(UserWarning):
    pass


def enforce_baseline(*, added: Sequence[str], removed: Sequence[str], blocking_from: date, message: str) -> None:
    if not added and not removed:
        return
    today = date.today()
    if blocking_from - today > MAX_GRACE:
        raise ValueError(f"blocking_from {blocking_from.isoformat()} is more than {MAX_GRACE.days} days away")
    if removed or today >= blocking_from:
        raise AssertionError(message)
    warnings.warn(
        f"Not blocking until {blocking_from.isoformat()}.\n{message}",
        RatchetGraceWarning,
        stacklevel=2,
    )
