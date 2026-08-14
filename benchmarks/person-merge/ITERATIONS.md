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
