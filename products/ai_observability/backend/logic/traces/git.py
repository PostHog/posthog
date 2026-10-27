from collections.abc import Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Self

from posthog.dataclasses import frozen

if TYPE_CHECKING:
    from .trace_queries import TraceEventRow

# The repo's real default branch is not known here, so these two names stand in for it.
_DEFAULT_BRANCHES = frozenset({"main", "master"})


def _stamp_order(row: "TraceEventRow") -> tuple[datetime, str]:
    # Ties break on the uuid so every read of the same rows picks the same event.
    return (row.timestamp, row.uuid)


@frozen
class GitRef:
    branch: str
    repo: str | None
    seen_at: datetime

    @property
    def is_default_branch(self) -> bool:
        return self.branch in _DEFAULT_BRANCHES

    @classmethod
    def from_rows(cls, rows: Iterable["TraceEventRow"]) -> Self | None:
        """The branch the trace's work ran on. A coding agent often starts on the default branch and creates the
        feature branch during the trace, so the latest stamp on another branch wins. A trace that never leaves the
        default branch keeps its first stamp."""
        stamped = [row for row in rows if row.git_branch]
        feature = [row for row in stamped if row.git_branch not in _DEFAULT_BRANCHES]
        row = max(feature, key=_stamp_order) if feature else min(stamped, key=_stamp_order, default=None)
        if row is None or row.git_branch is None:
            return None
        # The repo comes from the branch's own event, so a branch is never paired with another event's repo.
        return cls(branch=row.git_branch, repo=row.git_repo, seen_at=row.timestamp)
