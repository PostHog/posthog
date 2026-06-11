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

## 2026-06-11: Experiment-query CTE references multiply events scans; window functions beat percentile CTEs; verify with `ReadFromMergeTree` counts

**Context.** Directory-wide optimization pass over `products/experiments/backend/hogql_queries/`. Experiment metric queries are built as named-CTE chains (`exposures`, `metric_events`, `entity_metrics`, …); the printed ClickHouse SQL keeps the `WITH name AS (...)` form.

**Question.** How many times does each CTE actually execute, and what do de-duplicating rewrites buy?

**What we tried.** `EXPLAIN` on a ratio-metric-shaped query (the `exposures` CTE referenced three times: two pre-aggregation joins + final entity join) counted **5 `ReadFromMergeTree` nodes** — ClickHouse inlines and re-executes a CTE at every reference, exactly as the SKILL warns; counting `ReadFromMergeTree` nodes in EXPLAIN output is a fast, reliable way to audit this. The per-metric reference counts for experiment queries were: mean 2 scans, retention 4, ratio 5, winsorized variants ×2 on top (winsorized ratio = 10 events scans), because the `percentiles` CTE + `CROSS JOIN percentiles` shape re-executes the entire upstream `entity_metrics` chain. Each duplicated exposure scan also drags its `person_distinct_id_overrides` join and (with person-property test-account filters) a `person`-table join along with it.

Two rewrites measured on local dev ClickHouse (team 1 demo data, ~600k events, median of 5, `use_uncompressed_cache=0`; results byte-identical across shapes):

- Ratio: combining numerator+denominator into one conditional-aggregation scan and dropping redundant `exposures` references — read_rows 2.30M (3 refs) → 1.44M (2 refs) → 0.97M (1 ref, mean-shaped); memory flat.
- Winsorization: replacing the `percentiles` CTE + `CROSS JOIN` with `quantileExact(p)(value) OVER ()` window aggregates (breakdowns → `OVER (PARTITION BY breakdown_value_N)`) — read_rows and read_bytes exactly halved (1.75M→0.88M rows, 1.67GiB→856MiB), duration 610→455ms, memory flat (244→229MiB). The window form computes bounds in the same pass that reads the rows, so the doubling disappears.

**Caveats.** Local single-node, small parts, JSON unmaterialized (prod materializes `$feature_flag_response`, so prod exposure scans are cheaper per scan — the multiplication factor is unchanged). Wall-clock locally is noise; rows/bytes are the signal. Not yet timed on the Test Cluster.

**Takeaway.** In HogQL-built query chains, count references to every CTE that scans a fact table — each reference is a full re-execution, and shapes that look like "compute stats, then join them back" (`percentiles` + `CROSS JOIN`) silently double the whole upstream pipeline. Window aggregates (`agg(...) OVER (PARTITION BY ...)`) are the single-pass replacement for full-set/per-group bounds and cost no extra memory. HogQL supports parametric window aggregates (`quantileExact(0.9)(x) OVER ()`) end to end.

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
