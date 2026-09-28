"""Which paths a change adds, in the form SPEC section 3.6 asks a consumer to resolve them."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

from .matcher import SEP, normalize_path


def addition_paths(added: Iterable[str], exists: Callable[[str], bool]) -> list[str]:
    """The additions that the files in ``added`` make to the tree that ``exists`` answers for.

    ``added`` holds the files that a change creates. ``exists`` tells whether the tree before the
    change holds a repo-relative path. For each added file, the addition is the path nearest the
    root that the tree does not hold: the new directory above the file, or the file itself when its
    directory exists. The resolver walks only to the parent of a path, so the directory must be the
    path to resolve: its own ownership file then cannot remove what its parent names. A file that
    the tree already holds is no addition. The result keeps the first-seen order, without duplicates.
    """
    result: dict[str, None] = {}
    for path in added:
        normalized = normalize_path(path)
        if not normalized:
            continue
        parts = normalized.split(SEP)
        for depth in range(1, len(parts) + 1):
            candidate = SEP.join(parts[:depth])
            if not exists(candidate):
                result[candidate] = None
                break
    return list(result)


def addition_paths_on_disk(added: Iterable[str], repo_root: Path) -> list[str]:
    """``addition_paths`` against a checkout of the tree before the change."""
    return addition_paths(added, lambda path: (repo_root / path).exists())
