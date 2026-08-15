# Person merge optimization — experiment summary

Findings from the benchmark loop in this directory (iterations 0–5, full log in [ITERATIONS.md](./ITERATIONS.md), raw data in `results/`).
Everything here reproduces with `bin/pg-sandbox init && uv sync && uv run bench.py ...` — each claim cites its results file.

## The problem

Person merges where **both** distinct ids already have persons physically move every `posthog_persondistinctid` row from source to target.
The cost is linear in the source's mapping count: ~25 µs and ~630 WAL bytes per moved row, ~2 index writes per row (the `person_id` index defeats HOT), one FK check per row, and one ClickHouse override message per row — all inside a single lock-holding transaction.
A 10 000-mapping merge costs 253 ms and 6.3 MB of WAL in the benchmark (`current-iter0.json`); on production-sized tables, where the indexes are orders of magnitude larger and mostly cold, the per-row cost is strictly worse.
The `neither` and `one` scenarios are already O(1) and stay untouched by everything below.

## What was tried

| Approach                                                                               | Verdict                | Why                                                                                                                      |
| -------------------------------------------------------------------------------------- | ---------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `current` (production SQL, mirrored)                                                   | baseline               | Linear in source size; also quadratic under repeated re-merging (each merge re-moves all accumulated mappings)           |
| `union_find` — persons get `merged_into_id`; mappings never move                       | superseded             | Merge O(1), WAL flat; but reads and merges pick up ~3–5 µs per pointer hop, unbounded with chain depth                   |
| `union_find_compressed` — merge re-points all the source's children                    | dropped                | Flat reads, but O(children) writes per merge: quadratic on chains, 191 ms/step at depth 1000 — worse than baseline there |
| `union_find_compat` — union-find storage, today's per-mapping CH messages              | kept as contract floor | Measures exactly what the current ClickHouse override contract costs: reading + emitting N messages, no mapping writes   |
| `union_find_lazy` — pointer merge + walk-path compression + background pointer halving | **incumbent**          | Both hot paths flat at every depth and size tested                                                                       |

## Headline numbers

Merge cost by source size, `both` case (`*-full-iter3.json`):

| source mappings | current             | union_find_lazy family | compat (today's CH contract) |
| --------------- | ------------------- | ---------------------- | ---------------------------- |
| 1               | 2.2 ms / 5.4 KB WAL | 2.8 ms / 10.9 KB       | 2.8 ms / 10.8 KB             |
| 100             | 5.3 ms / 65 KB      | 2.7 ms / 10.9 KB       | 3.1 ms / 11.7 KB             |
| 1 000           | 25.5 ms / 636 KB    | 2.9 ms / 12.0 KB       | 6.2 ms / 12.1 KB             |
| 10 000          | 218 ms / 6.4 MB     | 4.1 ms / 12.0 KB       | 27.1 ms / 31.9 KB            |

Chain stress — 10 000 consecutive merges onto the same lineage (`union_find_lazy-chain10k-iter5.json`):

| depth  | lazy merge p50 | lazy reads (deep / mid / root) | background maintenance in window |
| ------ | -------------- | ------------------------------ | -------------------------------- |
| 1 000  | 2.6 ms         | 0.25 / 0.23 / 0.21 ms          | 0.46 s                           |
| 10 000 | 2.4 ms         | 0.21 / 0.24 / 0.21 ms          | 35.4 s                           |

The read path benchmarked is the production `get_person_by_distinct_id` shape — the query ingestion runs per event — and it stays indistinguishable from an unmerged person's read under the incumbent.
`current` and eager compression cannot complete the depth-10 000 chain (quadratic); uncompressed union-find completes it but reads decay to 30.5 ms.

## The ClickHouse contract is the remaining ceiling

Today ClickHouse needs one `person_distinct_id` override message per re-pointed mapping.
Any strategy honoring that must read N mappings and emit N messages per merge — that floor is measured at 27 ms for 10k mappings (`union_find_compat`), against 4 ms when a single person-level override message is allowed.
Even under the unchanged contract the WAL win (500x at 10k) survives, because reads are cheap and writes were the problem.

## Incumbent design in one paragraph

Add `posthog_person.merged_into_id` (NULL = live root).
A both-persons merge updates two person rows: target gets merged properties and a version bump, source gets the pointer — mapping, cohort, and feature-flag rows are touched only on the source _root_ (accumulated rows always sit there; this is what makes the merge O(1)).
Reads resolve pointer chains server-side; the merge's own root walk re-points the nodes it traversed (walk-path compression), and a background job bounds everyone else's depth.
Emissions are either one person-level override (needs a CH-side change) or today's per-mapping messages with versions derived as `mapping.version + root.version` (monotonic per distinct id, no mapping writes).

## Open items before this becomes a proposal

1. **Smarter maintenance.** Naive pointer halving rewrites the whole union per run (3.5 s at ~20k members). Known improvement: re-point only demoted roots at the final root — O(merges since last run), bounds depth at 2.
2. **Small-merge WAL gap.** Size-1 merges pay ~2x baseline WAL (two surviving person rows vs move+delete). A hybrid threshold (move inline when the source has few mappings) closes it.
3. **Person-table growth.** Merged person rows are never deleted; a background reaper (lazily re-home mappings, then drop the pointer row) restores steady-state storage.
4. **Vacuum sensitivity.** Pointer-churn maintenance bloats fast under any long-running transaction on the persons DB (measured: resolve degraded to seconds when a stale snapshot blocked vacuum). A deployment needs `idle_in_transaction_session_timeout`-style guard rails.
5. **Scale realism.** The benchmark preloads 150k mapping rows; production tables are orders of magnitude larger with cold indexes, which penalizes per-mapping-row strategies (`current`, and the compat emission read) further. Relative ratios are the signal; absolute latencies are optimistic.
6. **ClickHouse-side design** for the person-level override message, if the 7x beyond the contract floor is wanted.
