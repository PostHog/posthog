import os
import warnings
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

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
    notice = f"Not blocking until {blocking_from.isoformat()}.\n{message}"
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a") as summary:
            summary.write(f"### Ratchet grace period\n\n```text\n{notice}\n```\n\n")
    warnings.warn(notice, RatchetGraceWarning, stacklevel=2)
