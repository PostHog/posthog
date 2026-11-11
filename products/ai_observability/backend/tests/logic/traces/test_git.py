from datetime import datetime, timedelta

from parameterized import parameterized

from products.ai_observability.backend.logic.traces.git import GitRef
from products.ai_observability.backend.logic.traces.trace_queries import TraceEventRow

from .rows import T0, make_row

T1 = T0 + timedelta(seconds=30)


def _row(uuid: str, timestamp: datetime, branch: str | None = None, repo: str | None = None) -> TraceEventRow:
    return make_row(uuid=uuid, timestamp=timestamp, git_branch=branch, git_repo=repo)


@parameterized.expand(
    [
        ("no stamp", [_row("a", T0)], None),
        (
            "the latest stamped event wins",
            [_row("a", T0, "main"), _row("b", T1, "feat/rag", "acme/app")],
            GitRef(branch="feat/rag", repo="acme/app", seen_at=T1),
        ),
        (
            "input order does not matter",
            [_row("b", T1, "feat/rag", "acme/app"), _row("a", T0, "main")],
            GitRef(branch="feat/rag", repo="acme/app", seen_at=T1),
        ),
        (
            "a repo without a branch is no stamp",
            [_row("a", T0, "feat/rag"), _row("b", T1, None, "acme/other")],
            GitRef(branch="feat/rag", repo=None, seen_at=T0),
        ),
        (
            "the repo comes from the branch's own event",
            [_row("a", T0, "feat/one", "acme/app"), _row("b", T1, "feat/two")],
            GitRef(branch="feat/two", repo=None, seen_at=T1),
        ),
        (
            "equal timestamps pick the greater uuid",
            [_row("b", T0, "feat/b"), _row("a", T0, "feat/a")],
            GitRef(branch="feat/b", repo=None, seen_at=T0),
        ),
        (
            "equal timestamps in the other order",
            [_row("a", T0, "feat/a"), _row("b", T0, "feat/b")],
            GitRef(branch="feat/b", repo=None, seen_at=T0),
        ),
        (
            "a later default branch keeps the feature branch",
            [_row("a", T0, "feat/rag"), _row("b", T1, "main")],
            GitRef(branch="feat/rag", repo=None, seen_at=T0),
        ),
        (
            "only default branches, the earliest stamp wins",
            [_row("b", T1, "master", "acme/later"), _row("a", T0, "main", "acme/first")],
            GitRef(branch="main", repo="acme/first", seen_at=T0),
        ),
    ]
)
def test_from_rows(_name: str, rows: list[TraceEventRow], expected: GitRef | None) -> None:
    assert GitRef.from_rows(rows) == expected
