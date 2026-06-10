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
