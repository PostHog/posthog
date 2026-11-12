"""The files a change leaves unowned, for a coverage check on a repository that already has gaps."""

from __future__ import annotations

import os
import shutil
import tempfile
import subprocess
from collections.abc import Callable
from pathlib import Path

from .census import UNOWNED_TEAM, owning_team
from .matcher import SEP
from .resolver import GitRefSource, OwnersResolver, Resolution


def _git(repo_root: Path, *args: str, index: str | None = None) -> str:
    env = {**os.environ, "GIT_INDEX_FILE": index} if index else None
    command = ["git", "-C", str(repo_root), *args]
    return subprocess.run(command, capture_output=True, text=True, check=True, env=env).stdout


def newly_unowned(
    repo_root: Path,
    against: str,
    *,
    committed_only: bool = False,
    teams_only: bool = False,
    include: Callable[[str], object] | None = None,
) -> list[str]:
    """Files that are unowned now and were not at the merge base of HEAD and ``against``.

    A new file counts, and so does a file that lost its owners to a move or to an ownership file
    edit. A file that was already unowned at the merge base does not count, at its old path when
    the change moved it, so a gap the repository already has never counts against a change.

    The worktree is the files on disk that git does not ignore, tracked or not.
    ``committed_only`` reads HEAD and not the worktree, for a check on what a push carries.
    ``teams_only`` also counts a file that only ``@handles`` own, for a check that needs a team to
    route to. ``include`` limits the check to the paths it accepts, and no other path is resolved.
    """
    merge_base = _git(repo_root, "merge-base", against, "HEAD").strip()
    diff_args = ("diff", "--name-status", "-z", "--find-renames", "--relative", merge_base)
    if committed_only:
        head_source = GitRefSource(repo_root)
        head, files = OwnersResolver(repo_root, source=head_source), head_source.files
        diff = _git(repo_root, *diff_args, "HEAD")
    else:
        head = OwnersResolver(repo_root)
        # Git pairs a moved file with its old path only when the index holds the new path. A copy
        # of the index takes the untracked files, so the index of the repository does not change.
        with tempfile.TemporaryDirectory() as scratch:
            index = os.path.join(scratch, "index")
            current = _git(repo_root, "rev-parse", "--path-format=absolute", "--git-path", "index").strip()
            if os.path.exists(current):
                shutil.copy(current, index)
            _git(repo_root, "add", "--all", "--intent-to-add", ".", index=index)
            diff = _git(repo_root, *diff_args, index=index)
            files = frozenset(_git(repo_root, "ls-files", "-z", index=index).split("\0")) - {""}

    path_at_base: dict[str, str | None] = {}
    reowned: set[str] = set()
    ownership_filenames = head.ownership_filenames()
    fields = iter(diff.split("\0"))
    for status in fields:
        if not status:
            continue
        old = next(fields)
        new = next(fields) if status.startswith("R") else old
        if status.startswith(("A", "R")):
            path_at_base[new] = old if old != new and (include is None or include(old)) else None
        for path in (old, new):
            directory, sep, name = path.rpartition(SEP)
            if name in ownership_filenames:
                reowned.add(directory + sep)

    def lacks_owner(resolution: Resolution) -> bool:
        return owning_team(resolution) == UNOWNED_TEAM if teams_only else resolution.is_unowned

    # An ownership file decides only the paths below its directory, so a file outside the changed
    # directories keeps the owners it had.
    reowned_directories = tuple(reowned)
    candidates = sorted(
        path
        for path in files
        if (path in path_at_base or path.startswith(reowned_directories)) and (include is None or include(path))
    )
    unowned = [path for path in candidates if lacks_owner(head.resolve(path))]
    if not unowned:
        return []
    base = OwnersResolver(repo_root, source=GitRefSource(repo_root, merge_base))
    return [
        path
        for path in unowned
        if (before := path_at_base.get(path, path)) is None or not lacks_owner(base.resolve(before))
    ]
