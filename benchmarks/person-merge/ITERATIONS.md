# Iteration log

One entry per benchmark iteration. Baseline is `current` (production SQL, mirrored). Decisions and their reasons live here so dropped approaches stay dropped.

## Iteration 0 — baseline (`current`)

Environment: PG 16.13, preload 50k persons / 150k mappings, reps=20, single team.
Results: `results/current-iter0.json`, `results/current-iter0-contended.json`.

| case    | size   | p50 ms | p95 ms | WAL/op  | msgs/op |
| ------- | ------ | ------ | ------ | ------- | ------- |
| neither | –      | 1.98   | 7.20   | 9.9 KB  | 3       |
| one     | –      | 1.45   | 5.71   | 2.0 KB  | 2       |
| both    | 1      | 2.12   | 8.30   | 5.5 KB  | 3       |
| both    | 10     | 2.68   | 7.92   | 10.8 KB | 12      |
| both    | 100    | 5.39   | 10.97  | 65 KB   | 102     |
| both    | 1 000  | 25.35  | 39.73  | 636 KB  | 1 002   |
| both    | 10 000 | 253.24 | 380.37 | 6.3 MB  | 10 002  |

Contended (4 threads, shared target): both/100 p50 21.7 ms (~4x), both/1000 p50 99.0 ms (~4x). Lock waits on the shared target dominate; retries succeed.

Read path: ~0.2 ms p50 everywhere (unique-index lookup + PK join).

**Observations**

- The both case is linear at ~25 µs and ~630 WAL bytes per moved mapping. The curve, not the constant, is the problem.
- neither/one are already O(1) and cheap; candidates must not regress them (or the read path).
- Floor under the current CH contract: any merge of N mappings must read N mappings and emit N messages. Only a contract change (`new`-tagged emissions) can beat that floor.

**Decision**: baseline established, oracle green across all cases including contention. Proceed to challengers:

1. `union_find` — person-level indirection; mappings never move. Merge is O(1) writes. Read path follows a pointer chain (compressed in background). Supports both emission contracts to price the CH constraint.
2. `current_tuned` — best possible constant-factor version of today's shape (narrow RETURNING, single fsync'd txn layout, fillfactor). Control for "was a schema change even necessary".

## Iteration 1 — union-find indirection (`union_find`, `union_find_compat`)

Merges re-parent the source person (`posthog_person.merged_into_id`) instead of moving mapping rows.
Two person-row writes per merge regardless of source size; reads resolve pointer chains to the root.
Results: `results/union-find-iter1.json`, `results/union-find-compat-iter1.json`, `results/union-find-iter1-contended.json`.

| case | size   | current p50 | union_find p50   | compat p50       | current WAL | union_find WAL |
| ---- | ------ | ----------- | ---------------- | ---------------- | ----------- | -------------- |
| both | 1      | 2.12 ms     | 2.30 ms (1.09x)  | 3.54 ms (1.67x)  | 5.5 KB      | 9.8 KB (1.78x) |
| both | 100    | 5.39 ms     | 2.43 ms (0.45x)  | 2.90 ms (0.54x)  | 65 KB       | 11 KB (0.17x)  |
| both | 1 000  | 25.35 ms    | 2.45 ms (0.10x)  | 5.02 ms (0.20x)  | 636 KB      | 12 KB (0.02x)  |
| both | 10 000 | 253.24 ms   | 3.63 ms (0.014x) | 30.25 ms (0.12x) | 6.3 MB      | 13 KB (0.002x) |

Contended (4 threads, shared target): both/1000 p50 11.2 ms vs baseline 99.0 ms (~9x better); lock hold time no longer scales with source size.
neither/one and the read path are unregressed (~0.2 ms p50; chains are depth ≤ 1 in this workload).

**Observations**

- The curve is gone: merge cost is flat in source size. At 10k mappings, ~70x latency and ~480x WAL under the new contract.
- The contract floor is real and now measured: `union_find_compat` (same storage, per-mapping emissions with versions derived as `mapping.version + new root version`) pays 30 ms at 10k — all of it reading mappings and serializing messages. Still 8x latency and 500x WAL better than baseline, because reads are cheap and writes were the problem.
- Cost shifted, not vanished: tiny merges (size 1) regress ~10–70% latency and ~1.8x WAL because two person rows survive instead of one row moved + one deleted. A hybrid (physically move when the source has few mappings, re-parent when it has many) would take the best of both.
- Unpriced so far: pointer-chain depth under repeated re-merging (this workload never exceeds depth 1), background compaction/squash cost, and person-table growth (merged rows are never deleted).

**Decision**: union-find survives and is the incumbent challenger. Next iterations:

1. `hybrid` — threshold switch: move mappings inline for small sources, re-parent for large ones. Should erase the small-merge regression while keeping the flat curve.
2. chain-stress workload — repeatedly merge previously-merged persons to measure read-path decay with chain depth, and price the compaction job that bounds it.

## Iteration 2 — read benchmarks, chain stress, path compression (`union_find_compressed`)

The read path under test mirrors production `get_person_by_distinct_id` (`rust/personhog-replica/src/storage/postgres/person.rs`) / `fetchPerson` (Node): the query that runs on every ingested event, so any per-read regression multiplies by event volume, not merge volume.
Two additions to the harness:

- **Stratified post-merge reads** in every `both` phase: the target's own id, ids that arrived via the merge (these traverse indirection in pointer strategies), and untouched preload ids as control, each with p50/p95/p99 (`read_latency_detail_ms`).
- **`chain` workload**: at each step the current survivor is merged into a fresh person, so the first person's ids sit behind `depth` merges. Read decay for indirection strategies, write amplification for eager-move strategies. Models `$merge_dangerously` (production `$identify` refuses identified sources).

Results: `results/*-chain-iter2.json`, `results/*-both-iter2.json`.

Chain, 1000 ids/person, 5 chains, per step:

| depth | current merge p50 | current WAL/step | union_find merge p50 | union_find read p50 | compressed merge p50 | compressed read p50 |
| ----- | ----------------- | ---------------- | -------------------- | ------------------- | -------------------- | ------------------- |
| 1     | 34.3 ms           | 456 KB           | 4.6 ms               | 0.196 ms            | 4.3 ms               | 0.218 ms            |
| 8     | 180.1 ms          | 3.6 MB           | 3.6 ms               | 0.220 ms            | 3.6 ms               | 0.223 ms            |
| 16    | 349.7 ms          | 7.1 MB           | 5.1 ms               | 0.241 ms            | 3.4 ms               | 0.225 ms            |

**Observations**

- The feared read cliff does not materialize at moderate depth: uncompressed chains cost ~3 µs/hop through the recursive resolve (0.196 → 0.241 ms p50 at depth 16). But it is linear and unbounded, and the merge's lock-chase walk adds ~0.15 ms/hop on the write side too — depth must be bounded, not tolerated.
- Eager path compression bounds it: one extra `UPDATE ... WHERE merged_into_id = source` inside the merge transaction re-points the source's direct children, keeping every chain at depth ≤ 1. Reads and merges stay flat at any depth (0.22 ms / ~3 ms at depth 16). Its WAL cost grows with merges absorbed (0.7 → 6.9 KB/step at depth 16) — three orders of magnitude below `current`'s 7.1 MB/step.
- The chain workload exposes `current`'s hidden write amplification: accumulated mappings are physically re-moved on every subsequent merge — 10× re-merged ids means every later merge pays the full history again (34 → 350 ms/step, 16k messages by depth 16).
- Stratified reads in the `both` matrix confirm: merged-id reads under `union_find_compressed` are indistinguishable from control (~0.2 ms p50 at every size).

**Decision**: `union_find_compressed` supersedes plain `union_find` as the incumbent — same flat merge curve (2.8 ms / 12 KB WAL at 10k ids), reads bounded by construction. Remaining before this is proposal-ready:

1. `hybrid` small-merge threshold (the size-1 regression stands: ~2x WAL vs baseline).
2. Star-contention chain: thousands of sources into one survivor which is then re-merged — worst case for the compression UPDATE's child fan-out; needs measuring before trusting eager compression unconditionally.
3. Person-table growth accounting: merged rows are never deleted; a reaper/squash-style background job (re-home mappings lazily, then drop the pointer row) restores today's steady-state storage and can be priced with the same harness.

## Iteration 4 — deep chains: the tax curves to depth 10 000

Chain workload rerun with log-spaced checkpoints (1 id per person, 2 chains, preload 50k persons).
The union-find root walk moved server-side first (one recursive query + lock the root), replacing per-hop client round trips.
Results: `results/union_find-chain10k-iter4.json`, `results/union_find_compressed-chain1k-iter4.json`, `results/current-chain1k-iter4.json`.

| depth  | union_find merge p50 | union_find deep-read p50 | compressed merge p50        | compressed read p50 | current merge p50           | current read p50 |
| ------ | -------------------- | ------------------------ | --------------------------- | ------------------- | --------------------------- | ---------------- |
| 10     | 2.5 ms               | 0.24 ms                  | 2.7 ms                      | 0.21 ms             | 2.3 ms                      | 0.19 ms          |
| 100    | 3.1 ms               | 0.50 ms                  | 5.7 ms                      | 0.21 ms             | 5.3 ms                      | 0.20 ms          |
| 1 000  | 8.7 ms               | 3.96 ms                  | 191.3 ms                    | 0.24 ms             | 135.6 ms                    | 0.18 ms          |
| 10 000 | 54.3 ms              | 30.5 ms                  | – (quadratic, capped at 1k) | –                   | – (quadratic, capped at 1k) | –                |

Root reads (ids owned by the survivor) stay 0.2–0.9 ms for every strategy at every depth.

**Observations**

- Uncompressed union-find taxes are linear and gentle but unbounded: ~3 µs/hop on reads (30.5 ms at depth 10k), ~5 µs/hop on the merge's root walk (54 ms at depth 10k). WAL stays flat (~1 KB) at any depth.
- Eager compression buys flat reads (0.2 ms at every depth) by paying O(children) writes per merge — and a pure chain makes that quadratic: 191 ms/step at depth 1000, _worse than `current`_ (135 ms/step). Eager compression is the wrong unconditional default.
- `current` under chains re-moves the accumulated mappings each step: same quadratic blowup (135 ms/step, 342 KB WAL/step at depth 1000), which is the production status quo for repeat-merge teams today.
- The chain shape is adversarial for eager-fixup strategies and the status quo alike; only lazy indirection survives it — at a bounded, linear read tax.

**Decision**: neither always-eager nor never-compress wins alone. The production shape is lazy/amortized: keep the O(1) pointer merge, bound depth with compaction that is either piggybacked on merge walks (re-point the walked path) or a background sweep of nodes deeper than a threshold. Reads on replicas cannot compress, so the bound must come from the write side. Next: `union_find_lazy` with walk-path compression + depth-triggered background compaction, measured on both the chain and star workloads.

## Iteration 5 — lazy union-find: both hot paths flat to depth 10 000

`union_find_lazy` = O(1) pointer merge + walk-path compression (merge re-points only the nodes its root walk traversed) + background pointer halving every 500 merges (off the ingest path).
Two harness-found fixes along the way, both committed separately: phase-long snapshots in the harness were pinning dead tuples against vacuum (plus an `idle_in_transaction_session_timeout` guard in the sandbox), and the merge was collecting the source's whole union to re-home cohort/FF rows that provably always sit on the current root — the pure pointer merge is truly O(1) only after that fix; the union walk survives solely in the compat variant's per-mapping emissions, the current CH contract's floor.
Results: `results/union_find_lazy-chain10k-iter5.json`, `results/union_find_lazy-star-iter5.json`, `results/current-star-iter5.json`.

| depth  | merge p50 | deep read p50 | mid read p50 (never-walked) | root read p50 | maintenance in window |
| ------ | --------- | ------------- | --------------------------- | ------------- | --------------------- |
| 100    | 2.35 ms   | 0.21 ms       | 0.34 ms                     | 0.27 ms       | –                     |
| 1 000  | 2.57 ms   | 0.25 ms       | 0.23 ms                     | 0.21 ms       | 0.46 s                |
| 5 000  | 2.43 ms   | 0.28 ms       | 0.38 ms                     | 0.34 ms       | 10.0 s                |
| 10 000 | 2.42 ms   | 0.21 ms       | 0.24 ms                     | 0.21 ms       | 35.4 s                |

Star (300 sources into one target, 4 threads): lazy 6.9 ms p50 / 6.3 KB WAL vs current 8.3 ms p50 / 2.8 KB WAL; oracle green on both.

**Observations**

- Both hot paths are flat at any depth: merges ~2.4 ms, every read class 0.2–0.5 ms to depth 10 000. The chain workload that made `current` and eager compression quadratic and made uncompressed reads linear is fully absorbed.
- The residual tax lives in the background job, and naive pointer halving grows with union size: each run rewrites every union member log2(depth-since-flatten) times — 3.5 s per run at ~20k members (35 s across the last checkpoint window), 73 KB WAL amortized per merge. Identified improvement: re-point only internal nodes (demoted roots) at the final root — O(merges since last run) per run instead of O(union), bounding depth at 2. That is the next iteration if this graduates to a proposal.
- Production hazard surfaced by the stall: pointer-churn maintenance is unusually sensitive to long-running transactions on the persons DB — an idle snapshot blocks vacuum, maintenance churn bloats, and resolve degrades. Any real deployment needs the same idle-transaction guard rails the sandbox now has.
- Star topology needs no maintenance at all (children of a star point directly at the root by construction), so the common real-world merge shape pays only the O(1) merge.

**Decision**: `union_find_lazy` is the incumbent. The write tax of deep unions is gone from both hot paths; what remains is a tunable background cost with a known O(interval) improvement, and the small-merge WAL gap (~2x vs `current` at size 1) as the last open regression.
