# Person merge benchmark harness

Standalone, SQL-level harness for exploring faster implementations of the person merge operations that ingestion performs on Postgres:

- **neither** — `$identify` where neither distinct id has a person (create person with both ids)
- **one** — one distinct id has a person (attach the other id)
- **both** — both have persons (move every distinct id from source to target, merge properties, move cohort/feature-flag rows, delete source)

The **both** case is the problem: production moves each `posthog_persondistinctid` row with an `UPDATE`, so a source person with thousands of ids pays thousands of heap writes, ~2x that many index writes (the `person_id` index makes every update non-HOT), a per-row FK check, and one ClickHouse override message per row — all inside one transaction holding row locks.

The harness talks to Postgres directly (no Node pipeline) so candidate strategies are free to change schema and storage format entirely. Production SQL is mirrored statement-for-statement in the `current` strategy as the baseline; see `strategies/current.py` for the file-level mapping to `postgres-person-repository.ts`.

## Setup

```bash
bin/pg-sandbox init         # throwaway Postgres 16 on port 5544
uv sync
```

## Running

```bash
uv run bench.py --strategy current --cases neither,one,both \
    --sizes 1,10,100,1000,10000 --reps 20 --out results/current-iter0.json

# contended: N threads all merging different sources into one target person
uv run bench.py --strategy current --cases both --sizes 100,1000 \
    --reps 12 --concurrency 4 --contention shared-target \
    --out results/current-iter0-contended.json

uv run report.py results/current-iter0.json results/<candidate>.json
```

## What is measured

Latency percentiles alone would rank candidates wrong. Each phase records:

- merge wall latency (p50/p95/max + raw)
- WAL bytes per operation (`pg_current_wal_insert_lsn` delta) — the replication/checkpoint cost
- downstream emissions per operation, split by contract (see below)
- internal retries (concurrency-conflict pressure)
- read-path latency (`resolve(distinct_id)` p50/p95) — strategies that make merges cheap by making reads expensive must pay for it here

## The oracle

`oracle.py` is the contract of the experiment and runs on every rep:

1. every involved distinct id resolves to the surviving person
2. property precedence: target wins conflicts, source-only properties survive
3. cohort and feature-flag-hash-key rows follow the survivor
4. emission contract (below)
5. optional per-strategy storage consistency check (`verify_storage`)

A candidate that fails any check is not a candidate, whatever its numbers.

## Emission contracts

Today ClickHouse consumes one `person_distinct_id` override message per re-pointed mapping. Emissions are tagged:

- `contract="current"` — message shapes that exist today; a strategy emitting only these is shippable without touching the ClickHouse side
- `contract="new"` — requires a ClickHouse-side change (e.g. a single person-level override under an indirection scheme)

Preserving the current contract puts a floor under every candidate: a merge of N mappings must at least read N mappings and emit N messages. Strategies may support both modes so the report can show exactly what the contract costs.

## The iteration loop

Recorded in `ITERATIONS.md`, one entry per iteration:

1. pick a candidate (or a variant of a live candidate), implement it as a strategy
2. run the same workload matrix as the baseline, oracle always on
3. `report.py` against the baseline and the candidate's previous iteration
4. decide: iterate further, or drop the approach when it has no more headroom and does not beat the incumbent — record the reason either way

Results files are committed under `results/` so every decision stays reproducible.

## Caveats

- Postgres 16 here vs 15 in production docker-compose — relative comparisons only.
- The baseline mirrors the legacy (non-tombstone) path, which is today's default. The tombstone/lifecycle-mark rollout adds constant per-transaction overhead and does not change how cost scales with moved mappings.
- Seeded data is synthetic (invented ids, `example`-style values); nothing here derives from customer data.
