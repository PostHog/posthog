"""Shared Hypothesis example-database wiring for the HogQL parser/printer PBTs.

``parser_pbt_corpus/`` is the home for a committable
``DirectoryBasedExampleDatabase``, but it **ships empty by default** — the PBT
tooling only runs in offline analysis (never CI), so a shipped seed wasn't worth
committing megabytes of opaque blobs (see that directory's README). The
*mechanism* is wired here; the *content* is opt-in.

Per Hypothesis's own recommendation (see ``MultiplexedDatabase`` /
``ReadOnlyDatabase`` docstrings), the default the tooling uses is
``MultiplexedDatabase(local, ReadOnlyDatabase(committed))``:

  - whatever is committed under ``parser_pbt_corpus/`` (nothing, by default) is
    replayed first on every run, but **read-only**, so a normal test run or
    grind never rewrites it — no binary-diff churn on `git status`;
  - newly-discovered failing / Pareto-front examples are written only to the
    developer's local ``.hypothesis/examples`` database.

If a shared seed ever earns its keep, populate it read-write and commit the
blobs::

    PYTHONPATH=. python posthog/hogql/scripts/pbt_diagnostic.py --update-corpus ...

which points a read-write database straight at the committed directory. The blob
format is stable only while Hypothesis stays pinned (``hypothesis~=6.151.9`` in
``pyproject.toml``, exact in ``uv.lock``); the directory lives outside
``.hypothesis/`` so the repo-wide ``.hypothesis`` gitignore doesn't sweep it up.
"""

from __future__ import annotations

from pathlib import Path

from hypothesis.configuration import storage_directory
from hypothesis.database import DirectoryBasedExampleDatabase, ExampleDatabase, MultiplexedDatabase, ReadOnlyDatabase

# Committed corpus seed. Outside `.hypothesis/` on purpose (that path is
# gitignored repo-wide); this directory is tracked.
PARSER_PBT_CORPUS_DIR: Path = Path(__file__).resolve().parent / "parser_pbt_corpus"


def committed_corpus_db() -> ExampleDatabase:
    """Read-write handle straight to the committed corpus seed. Used only by the
    deliberate ``pbt_diagnostic.py --update-corpus`` population path — everything
    else reads the seed through :func:`shared_corpus_database` (read-only).

    Annotated ``ExampleDatabase`` (the base) rather than the concrete subclass:
    Hypothesis's ``_EDMeta`` metaclass types ``DirectoryBasedExampleDatabase(...)``
    construction as returning the base ``ExampleDatabase``."""
    return DirectoryBasedExampleDatabase(PARSER_PBT_CORPUS_DIR)


def shared_corpus_database(local: ExampleDatabase | None = None) -> ExampleDatabase:
    """Default database for the PBT tooling: replay the committed seed read-only,
    write new examples to a local read-write database. So running the PBTs
    reproduces committed regressions and warm-starts from the committed coverage
    front, but never churns the committed blobs.

    ``local`` defaults to Hypothesis's standard ``.hypothesis/examples`` directory
    (so locally-found failures land where Hypothesis normally caches them); pass
    an explicit database to override (e.g. an ``InMemoryExampleDatabase`` for a
    hermetic run)."""
    if local is None:
        local = DirectoryBasedExampleDatabase(storage_directory("examples"))
    committed = ReadOnlyDatabase(DirectoryBasedExampleDatabase(PARSER_PBT_CORPUS_DIR))
    return MultiplexedDatabase(local, committed)
