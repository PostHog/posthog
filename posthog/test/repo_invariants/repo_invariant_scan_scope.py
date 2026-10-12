"""Narrow the file walk of a repo invariant to a few directories.

CI sets REPO_INVARIANTS_SCAN_SCOPE on a pull request that changes only warehouse source vendors,
to the vendor directories it changed. A vendor cannot import another vendor, so such a diff
cannot change what a walk finds outside those directories. Each walk then reads only those
directories and compares only the baseline lines inside them. Without the variable, every walk
reads all of its roots.
"""

import os
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

SCAN_SCOPE_VARIABLE = "REPO_INVARIANTS_SCAN_SCOPE"


def _inside(path: str, directory: str) -> bool:
    return PurePosixPath(path).is_relative_to(PurePosixPath(directory))


class ScanScope:
    def __init__(self, directories: tuple[str, ...] | None) -> None:
        # None means the whole repo. An empty tuple means no directory at all.
        self.directories = directories

    @classmethod
    def from_environment(cls) -> "ScanScope":
        value = os.environ.get(SCAN_SCOPE_VARIABLE)
        return cls(None if value is None else tuple(value.split()))

    def roots(self, roots: Iterable[str]) -> list[str]:
        """The repo-relative directories to walk: the roots, or the scope directories inside them."""
        roots = list(roots)
        if self.directories is None:
            return roots
        return [directory for directory in self.directories if any(_inside(directory, root) for root in roots)]

    def covers(self, path: str) -> bool:
        """Whether a repo-relative path sits in the scope."""
        if self.directories is None:
            return True
        return any(_inside(path, directory) for directory in self.directories)

    def walk(self, repo_root: Path, roots: Iterable[Path], pattern: str) -> list[tuple[Path, Path]]:
        """Each file that matches the pattern in the scope, with the root it sits under."""
        files: list[tuple[Path, Path]] = []
        for root in roots:
            for directory in self.roots([root.relative_to(repo_root).as_posix()]):
                files.extend((root, path) for path in (repo_root / directory).rglob(pattern))
        return files

    def covers_root_relative(self, repo_root: Path, roots: Iterable[Path], path: str) -> bool:
        """Whether a path written relative to one of the roots sits in the scope."""
        return any(self.covers((root / path).relative_to(repo_root).as_posix()) for root in roots)
