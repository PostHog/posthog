"""The files a change leaves unowned, for a coverage check on a repository that already has gaps."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .matcher import SEP
from .resolver import GitRefSource, OwnersResolver


def _git(repo_root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo_root), *args], capture_output=True, text=True, check=True).stdout


def newly_unowned(repo_root: Path, against: str, *, committed_only: bool = False) -> list[str]:
    """Files that are unowned now and were not at the merge base of HEAD and ``against``.

    A new file counts, and so does a file that lost its owners to a move or to an ownership file
    edit. A file that was already unowned at the merge base does not count, at its old path when
    the change moved it, so a gap the repository already has never counts against a change.

    The worktree includes the files git does not track yet, except the ignored ones.
    ``committed_only`` reads HEAD and not the worktree, for a check on what a push carries.
    """
    merge_base = _git(repo_root, "merge-base", against, "HEAD").strip()
    diff = _git(
        repo_root, "diff", "--name-status", "-z", "--find-renames", merge_base, *(["HEAD"] if committed_only else [])
    )
    if committed_only:
        head_source = GitRefSource(repo_root)
        head, files = OwnersResolver(repo_root, source=head_source), sorted(head_source.files)
    else:
        head = OwnersResolver(repo_root)
        untracked = [
            path for path in _git(repo_root, "ls-files", "--others", "--exclude-standard", "-z").split("\0") if path
        ]
        files = sorted([*head.tracked_files(), *untracked])
        diff += "".join(f"A\0{path}\0" for path in untracked)

    path_at_base: dict[str, str | None] = {}
    reowned_directories: set[str] = set()
    ownership_filenames = head.ownership_filenames()
    fields = iter(diff.split("\0"))
    for status in fields:
        if not status:
            continue
        old = next(fields)
        new = next(fields) if status.startswith("R") else old
        if status.startswith(("A", "R")):
            path_at_base[new] = old if old != new else None
        for path in (old, new):
            directory, _, name = path.rpartition(SEP)
            if name in ownership_filenames:
                reowned_directories.add(directory)

    # An ownership file decides only the paths below its directory, so a file outside the changed
    # directories keeps the owners it had.
    candidates = [
        path
        for path in files
        if path in path_at_base
        or any(not directory or path.startswith(directory + SEP) for directory in reowned_directories)
    ]
    unowned = head.unowned(candidates)
    if not unowned:
        return []
    base = OwnersResolver(repo_root, source=GitRefSource(repo_root, merge_base))
    return [
        path
        for path in unowned
        if (before := path_at_base.get(path, path)) is None or not base.resolve(before).is_unowned
    ]
