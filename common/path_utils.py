"""Repo-root discovery helper.

Walks up the filesystem from a starting path until it finds ``manage.py``,
the marker file at the repository root. Centralizes what used to be
open-coded ``Path(__file__).parent.parent.parent...`` chains and
``REPO_ROOT = ...`` assignments scattered across the codebase.

``manage.py`` is used as the marker (rather than e.g. ``hogli.yaml``) because
it is the only top-level file guaranteed to ship in every Django runtime
context — the dev checkout, production Docker images, and CI runners.

Zero third-party deps so it can be imported from settings, tests, scripts,
and Django management commands alike.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT_MARKER = "manage.py"


def find_repo_root(start: str | os.PathLike[str] | None = None) -> Path:
    """Return the repository root by walking up looking for ``manage.py``.

    When ``start`` is omitted, defaults to the ``__file__`` of the immediate
    caller. Pass an explicit path (typically ``__file__``) when calling from
    a context where stack inspection is unreliable (e.g. ``exec``'d code).

    Raises ``FileNotFoundError`` if no marker is found before the filesystem
    root — that almost always means the code is being run outside a posthog
    checkout, and silently falling back to cwd would mask a real bug.
    """
    if start is None:
        caller = sys._getframe(1).f_globals.get("__file__")
        start = caller if caller is not None else os.getcwd()

    start_path = Path(start).resolve()
    if start_path.is_file():
        start_path = start_path.parent

    for parent in (start_path, *start_path.parents):
        if (parent / REPO_ROOT_MARKER).is_file():
            return parent

    raise FileNotFoundError(f"could not find repo root: no {REPO_ROOT_MARKER!r} above {start_path}")
