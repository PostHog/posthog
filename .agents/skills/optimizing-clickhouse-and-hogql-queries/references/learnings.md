# Optimization learnings log

Append-only record of optimization experiments and surprising findings, so future agents (and humans) don't relearn the same lessons. Each entry is a small case study: where the question came up, what we tried, the numbers, and the takeaway. New entries go on top.

When you find something that surprised you, add it here, especially if it contradicts the smell descriptions in `SKILL.md`. Real numbers from the Test Cluster or production beat plausible-sounding rules of thumb.

> **⚠️ This file is in a public OSS repo. Do not include customer data.**
>
> No raw person / group / distinct_id UUIDs, no custom property names or values, no team or org names, no row samples, no precise customer-specific operational scale (exact row counts, durations tied to a specific team). Use placeholders (`<bound_uuid>`, `<custom_property>`, `<team_id>`) or describe the shape (`a 1M-person slice picked by sort offset`, `tens of millions of persons`). PostHog's own team 2 is fine to name as the canonical Test Cluster target; redact other team IDs. PostHog-standard properties prefixed with `$` (`$browser`, `$os`, `$current_url`) are safe; customer-defined properties are not.

Suggested entry format:

```markdown
## YYYY-MM-DD: <short title>

**Context.** Where the question came up (file, query type, why we were looking).

**Question.** What were we trying to learn.

**What we tried.** Variants compared, with the relevant SQL fragments.

**Numbers.** Median of N from `system.query_log`, with read_bytes and memory_usage.

**Caveats.** What the measurement environment couldn't show.

**Takeaway.** One or two sentences a future reader can act on.
```

---

## 2026-06-09: Minmax skip indexes are net-negative for negation-only filters; ignore them per query instead of disabling skip indexes

**Context.** A nightly cache-warming TrendsQuery with an all-time date range ran ~60s per shard on cold replicas while reading only a few MiB. `query_log` showed long wall, low CPU, no CPU-starvation wait (so not cluster load). The 1 Hz production profiler (`system.trace_log`, symbolized in-database with `demangle(addressToSymbol(...))` and `SETTINGS allow_introspection_functions=1` via clusterAllReplicas so symbolization runs on the owning host) attributed the time to `filterMarksUsingIndex` → `MergeTreeIndexReader::read` → `MergeTreeIndexGranuleMinMax::deserializeBinary`, mark loading (`MergeTreeMarksLoader::loadMarksSync`), and a mutex under `CachedCompressedReadBuffer::nextImpl`.

**Question.** PK pruning had already reduced the scan to a few thousand granules across >1k parts, so why did skip-index evaluation cost hundreds of thread-seconds, and what is the safe fix at the HogQL layer?

**What we tried.** Mechanics first: per part and per index, ClickHouse loads the entire index marks file (one entry per granule of the part, regardless of how narrow the candidate ranges are — millions of mark entries for a query that finally selected a few hundred marks), and minmax granules deserialize Field-by-Field through a cache wrapper whose global mutex serializes all index reads on the node (zero-capacity `index_uncompressed_cache` is the default; bypass landed upstream in ClickHouse PR 104063, after 26.3). The query's only applied-but-useless index condition was a bare `notEquals(mat_col, const)`: a minmax condition for `!=` can only exclude granules where min == max == the excluded value (it pruned ~1.5% of granules for ~1/3 of the index-analysis cost). Benchmarked three arms on warm production replicas, host-paired, n=15 per arm, `use_query_condition_cache=0`: A baseline, B `ignore_data_skipping_indices='minmax_<col>'` for the negated column only, C ignore all three applied indexes.

**Numbers.** Medians from `query_log`: B vs A cut `FilteringMarksWithSecondaryKeysMicroseconds` from 1873ms to 811ms (−57%), `CompressedReadBufferBytes` from 689MB to 363MB (−47%), OS IO wait from 1510ms to 720ms (−53%), with identical results. C (no skip indexes at all) read 3.4× more rows and +62% CPU — the positively-used timestamp and equality indexes earn their keep.

**Caveats.** Warm-replica numbers; on cold replicas the same mark/index reads were the bulk of a 60s wall, so the relative win there is larger. `notILike`/`notLike`/regex negations build no usable minmax condition and are already skipped by ClickHouse — the waste is specific to `!=` / `NOT IN`, which build technically-usable conditions.

**Takeaway.** When a minmax-indexed materialized column is referenced only under `!=` / `NOT IN`, evaluating the index costs far more than it prunes; the safe surgical fix is `ignore_data_skipping_indices` (ignoring a skip index can only widen reads, never change results), not `use_skip_indexes=0`. The HogQL printer now does this automatically (modifier `ignoreNegationOnlySkipIndexes`, default on). Also remember: `EXPLAIN indexes=1` granule counts can massively understate skip-index cost — the cost scales with parts × per-part mark-file size, not with candidate granules.

---

## 2026-05-28: Dropping `FROM person FINAL` via `argMax` is worse than the original; materialization is the actual win

**Context.** `posthog/temporal/messaging/backfill_precalculated_person_properties_workflow.py` builds a raw ClickHouse query that does `SELECT id, JSONExtract(properties, '<key>', 'String'), ... FROM person FINAL WHERE team_id = ... AND id BETWEEN ... AND is_deleted = 0 ORDER BY id FORMAT JSONEachRow`. We flagged the `FINAL` as a smell.

**Question.** Does dropping `FINAL` via the textbook `argMax(properties, version) GROUP BY id` rewrite actually make the query faster?

**What we tried.** Three variants on the Test Cluster, team 2, an `id <= <bound_uuid>` slice picked at the 1-millionth-row sort offset (so the WHERE prefix covers exactly the team_id + id sort key for ~1M persons), all returning the same small set of distinct `$browser` values:

- **A**: `FROM person FINAL` + `JSONExtract(properties, '$browser', 'String')`
- **B**: `argMax(properties, version) GROUP BY id HAVING argMax(is_deleted, version) = 0` + `JSONExtract` over the winning blob
- **C**: `argMax(pmat_$browser, version) GROUP BY id HAVING argMax(is_deleted, version) = 0` (materialized column)

**Numbers.** Median of 5 from `system.query_log`, `use_uncompressed_cache=0`:

| Variant                                 | Duration (ms) | Read bytes  | Peak memory |
| --------------------------------------- | ------------- | ----------- | ----------- |
| A: `FINAL` + `JSONExtract`              | 107           | 1.27 GB     | 308 MB      |
| B: `argMax(properties)` + `JSONExtract` | 156           | 1.27 GB     | **3.0 GB**  |
| C: `argMax(pmat_$browser)`              | **23**        | **37.9 MB** | 238 MB      |

B was 46% slower than A and used ~10× the memory. C was 4.6× faster than A and read 33× fewer bytes.

**Caveats.** Team 2's snapshot has `count() == countDistinct(id)` (tens of millions of each), meaning background merges had already deduplicated the table before we measured. `FINAL` therefore had no actual merge work to do, only the planner overhead and the no-parallel-reads cost. On a team with active person updates, A's wall-clock and memory would shift up; B would shift even more (argMax over more rows per group). The relative ordering of "materialization dominates" should hold.

**Takeaway.** The blanket "FINAL bad, argMax good" framing is wrong in at least one important case: argMax over a wide column (`properties` blobs) buffers the winning value per group in the GROUP BY hash table, which can blow memory up by 10× while making the query slower than just letting `FINAL` stream. The safe rewrite hierarchy for moving off `FROM ... FINAL` is: (1) use a materialized column if one exists, (2) argMax over a narrow column you actually need, (3) only fall back to argMax over the wide column as a last resort. If none of those apply, `FINAL` may genuinely be the cheapest option.
