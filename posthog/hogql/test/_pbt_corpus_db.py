"""Shared Hypothesis example-database wiring for the HogQL parser/printer PBTs.

``parser_pbt_corpus/<hypothesis-version>/`` is a per-machine, per-Hypothesis
``DirectoryBasedExampleDatabase`` — the parent directory is tracked but every
subdirectory under it is ``.gitignore``\\ d. Each dev can populate their own
seed locally (e.g. with the future diagnostic CLI's ``--update-corpus`` mode,
or directly via :func:`committed_corpus_db`) and benefit from warm-starts and
replays on their own machine without pushing opaque binary blobs to the repo.

The storage path always resolves to the **main worktree's** copy of the
directory, so every git worktree of the same checkout shares one seed (see
:func:`_resolve_corpus_dir`). Without that, devs juggling worktrees would end up
with a different seed per branch — defeating the "persists between runs on this
machine" goal.

The Hypothesis-version segment keeps each version's blobs in its own
subdirectory: Hypothesis's blob format is only stable within a pinned version,
and without segmentation a bump would silently mis-replay stale blobs against a
newer codec.

Per Hypothesis's own recommendation (see ``MultiplexedDatabase`` /
``ReadOnlyDatabase`` docstrings), the default the tooling uses is
``MultiplexedDatabase(local, ReadOnlyDatabase(committed))``:

  - whatever the dev has put under ``parser_pbt_corpus/<version>/`` is replayed
    first on every run, but **read-only**, so a normal test run or grind never
    rewrites it — no churn from accumulated PBT failures piling up there;
  - newly-discovered failing / Pareto-front examples are written only to the
    developer's local ``.hypothesis/examples`` database (Hypothesis's default
    location).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import hypothesis
from hypothesis.configuration import storage_directory
from hypothesis.database import DirectoryBasedExampleDatabase, ExampleDatabase, MultiplexedDatabase, ReadOnlyDatabase


def _resolve_corpus_dir() -> Path:
    """Resolve the corpus dir to a ``parser_pbt_corpus/<hypothesis-version>/``
    subdirectory of the **main worktree's** source tree, so every git worktree
    of the same checkout shares one seed.

    Two things:

    1. ``git rev-parse --git-common-dir`` resolves to the shared ``.git`` for
       all worktrees of this repo; its parent is the main worktree's top-level.
       Without this, ``Path(__file__).parent / "parser_pbt_corpus"`` resolves to
       *this* worktree's source tree, and devs juggling worktrees end up with a
       different seed per branch.
    2. Hypothesis's blob format is only stable within a pinned version (see
       ``DirectoryBasedExampleDatabase``). The version segment keeps each
       Hypothesis version's blobs in its own subdirectory so a bump never
       silently mis-replays stale entries against a newer codec.

    Falls back to ``Path(__file__).parent / "parser_pbt_corpus" / <version>`` if
    git isn't available or this isn't a checkout — still per-machine and
    version-segmented, just per-checkout instead of shared across worktrees.
    """
    here = Path(__file__).resolve().parent
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=here,
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return here / "parser_pbt_corpus" / hypothesis.__version__
    common_dir = Path(result.stdout.strip())
    if not common_dir.is_absolute():
        common_dir = (here / common_dir).resolve()
    main_worktree_root = common_dir.parent
    return main_worktree_root / "posthog" / "hogql" / "test" / "parser_pbt_corpus" / hypothesis.__version__


# Per-machine corpus seed shared across every git worktree of this checkout,
# segmented by Hypothesis version (e.g. `parser_pbt_corpus/6.151.9/`). The
# parent dir is tracked in-tree (so the README + `.gitignore` are discoverable
# on whichever branch you're on), but every subdir under it is `.gitignore`d —
# populated and used only locally. Outside `.hypothesis/` on purpose: that path
# is gitignored repo-wide, which would sweep this dir up under it.
PARSER_PBT_CORPUS_DIR: Path = _resolve_corpus_dir()


def committed_corpus_db() -> ExampleDatabase:
    """Read-write handle straight to the local corpus seed. Use only when
    deliberately populating the seed — everything else reads through
    :func:`shared_corpus_database` (read-only).

    Annotated ``ExampleDatabase`` (the base) rather than the concrete subclass:
    Hypothesis's ``_EDMeta`` metaclass types ``DirectoryBasedExampleDatabase(...)``
    construction as returning the base ``ExampleDatabase``."""
    return DirectoryBasedExampleDatabase(PARSER_PBT_CORPUS_DIR)


def shared_corpus_database(local: ExampleDatabase | None = None) -> ExampleDatabase:
    """Default database for the PBT tooling: replay the local seed read-only,
    write new examples to a local read-write database. So running the PBTs
    warm-starts from the local seed and persists new failures, but never churns
    the seed blobs from the test path.

    ``local`` defaults to Hypothesis's standard ``.hypothesis/examples`` directory
    (so locally-found failures land where Hypothesis normally caches them); pass
    an explicit database to override (e.g. an ``InMemoryExampleDatabase`` for a
    hermetic run)."""
    if local is None:
        local = DirectoryBasedExampleDatabase(storage_directory("examples"))
    committed = ReadOnlyDatabase(DirectoryBasedExampleDatabase(PARSER_PBT_CORPUS_DIR))
    return MultiplexedDatabase(local, committed)
