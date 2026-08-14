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
