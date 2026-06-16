# Parser PBT corpus (per-machine Hypothesis example database)

This directory is a [Hypothesis example database](https://hypothesis.readthedocs.io/en/latest/database.html)
(`DirectoryBasedExampleDatabase`) for the HogQL parser-parity property tests.

**Contents are `.gitignore`d.** Only this README and the `.gitignore` are tracked. Each developer
populates their own seed locally; nothing ever gets pushed to the remote.

The actual storage lives at `parser_pbt_corpus/<hypothesis-version>/` in the
**main worktree's** copy of this directory, even when the PBT runs from another
worktree (see `_resolve_corpus_dir` in [`_pbt_corpus_db.py`](../_pbt_corpus_db.py)).
One seed per machine + per Hypothesis version, not one per worktree.

The version segmentation matters because Hypothesis's blob format is only
stable within a pinned version — without it, a `hypothesis` bump would silently
mis-replay stale blobs against the newer codec. Old version dirs are inert
after a bump; they're harmless and can be deleted if you care about the disk.

## Why local-only?

A committed seed would ship megabytes of opaque binary blobs to the repo and churn
on every PBT run that finds a new interesting example. The PBT tooling already runs
**offline only** (never in CI), so a shared seed adds noise without solving a real
problem. Persistence between runs _on the same machine_ is what matters — and
Hypothesis's local cache combined with this dir handles that without any commits.

## How runs use this dir

The tooling wires this as `MultiplexedDatabase(local, ReadOnlyDatabase(committed))`
(see [`_pbt_corpus_db.py`](../_pbt_corpus_db.py)):

- whatever's in this dir is replayed first on every PBT run, but **read-only**,
- new examples / Pareto-front entries land in `.hypothesis/examples`
  (Hypothesis's default per-machine cache).

An empty dir is fine — it just means no warm-start. Everything else works
normally.

## Populating the seed locally

Use the read-write handle returned by `committed_corpus_db()` in
[`_pbt_corpus_db.py`](../_pbt_corpus_db.py).
