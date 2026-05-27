# Parser PBT corpus (committed Hypothesis example database)

This directory is the home for a committed [Hypothesis example database](https://hypothesis.readthedocs.io/en/latest/database.html)
(`DirectoryBasedExampleDatabase`) for the HogQL parser-parity property tests.
It is **intentionally empty by default** — only this README is tracked.

## Why empty?

The PBT tooling that would populate it (the `pbt_diagnostic.py` grind and the
`RUN_PBT`-gated pytest PBTs) only runs in **offline analysis**, never in CI. A
shipped corpus would just warm-start those offline runs slightly — the grind
rebuilds coverage in seconds, and real divergences already land in
`pbt_diagnostic.py --write-divergences` JSONL and hardcoded regression tests in
`_test_parser.py`. So the marginal value didn't justify committing megabytes of
opaque blobs. The _mechanism_ is wired up (see
[`_pbt_corpus_db.py`](../_pbt_corpus_db.py)); the _content_ is opt-in.

## How runs use this dir

The tooling wires this as `MultiplexedDatabase(local, ReadOnlyDatabase(committed))`:
runs replay whatever is committed here (nothing, by default) read-only, and
write new examples only to the developer's local `.hypothesis/examples`. So an
empty dir simply means no warm-start — everything else works normally and
nothing here churns.

## Opting in to a committed seed

If a shared seed ever proves worth it (e.g. to pin specific regression inputs so
they replay for everyone), populate it read-write and commit the resulting blobs:

```bash
PYTHONPATH=. python posthog/hogql/scripts/pbt_diagnostic.py \
    --update-corpus --rule expr --n 20000
git add posthog/hogql/test/parser_pbt_corpus && git commit ...
```

The blob format is stable only while Hypothesis stays pinned (`hypothesis~=6.151.9`
in `pyproject.toml`, exact in `uv.lock`); on a major bump, stale entries are
ignored on replay (not fatal). Keep this dir empty unless a seed earns its keep.
