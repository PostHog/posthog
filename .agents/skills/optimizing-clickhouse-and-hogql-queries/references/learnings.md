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

## 2026-06-10: A minmax skip index on a mixed-content string column does not rescue unbounded point lookups; UUIDv7 ids carry their own time bound

**Context.** Replay capture diagnostics (`frontend/src/scenes/session-recordings/components/replayCaptureDiagnosticsPanelLogic.ts`): `SELECT properties FROM events WHERE $session_id = {sid} ORDER BY timestamp DESC LIMIT 1` with no timestamp predicate. `$session_id` is a materialized column with `INDEX minmax_$session_id ... TYPE minmax GRANULARITY 1`, and session ids are UUIDv7 (time-ordered), so on paper the skip index should prune almost everything even without a timestamp bound.

**Question.** Does the minmax skip index make the unbounded single-session lookup cheap, or does it still need a timestamp bound?

**Numbers.** Median of 5, Test Cluster, team 2 (history back to 2020), a real high-volume session id, `use_query_condition_cache=0`:

| Variant                     | Duration (ms) | Read rows | Read bytes |
| --------------------------- | ------------- | --------- | ---------- |
| no timestamp bound          | 16,485        | 2.44B     | 76.8 GB    |
| `timestamp >=` 90d          | 4,993         | 452M      | 20.8 GB    |
| UUIDv7-derived window (~7d) | 503           | 35.7M     | 10.4 GB    |

**Caveats.** The exact pruning loss depends on the team's mix of `$session_id` values; a team with only UUIDv7 ids might see better index behavior. Not measured per-mix.

**Takeaway.** The minmax index did not save the unbounded query: the column also holds the literal string `'null'` (millions of rows/day on team 2) and other non-UUID values, so each granule's `[min, max]` range is wide enough to contain any UUIDv7 and almost nothing is excluded. Minmax on strings only prunes when values correlate tightly with insertion order across the _whole_ column, not just the subset you care about. The structural fix is the same as any single-entity lookup: carry a timestamp bound. When the id is a UUIDv7, the client can derive that bound from the id's embedded 48-bit ms timestamp (plus clock-skew slack and a fallback window for non-parsing ids): 33x faster and 68x fewer rows than the unbounded form here.

---

## 2026-06-10: Pre-filtering a window-function scan with an IN-subquery doubled the cost; JSON parsing dominates, window sorts are cheap

**Context.** MCP analytics "neighbors before/after" queries (`products/mcp_analytics/frontend/mcpAnalyticsToolDetailLogic.ts`): a CTE scans all 7 days of a team's `mcp_tool_call` events, computes `lagInFrame`/`leadInFrame` over every conversation, then filters to one target tool. Looked like wasted work: most conversations don't contain the target tool.

**Question.** Does adding `AND conv_id IN (SELECT DISTINCT conv_id ... WHERE tool = '<target>')` to shrink the window input make the query faster?

**What we tried.** Original shape vs the IN-subquery pre-filter, on the Test Cluster, team 2, over a ~253k-event `mcp_tool_call` slice, for both a rare tool (~2% of calls) and the dominant tool (~48% of calls). All property access via `JSONExtractString(properties, ...)` (no materialized columns for these on the Test Cluster).

**Numbers.** Median of 5 from `system.query_log`, `use_uncompressed_cache=0, use_query_condition_cache=0`:

| Variant                     | Duration (ms) | Read rows | Read bytes |
| --------------------------- | ------------- | --------- | ---------- |
| original, rare tool         | 355           | 322k      | 2.87 GB    |
| pre-filtered, rare tool     | 607           | 651k      | 5.73 GB    |
| original, dominant tool     | 387           | 322k      | 2.87 GB    |
| pre-filtered, dominant tool | 721           | 739k      | 5.74 GB    |

The "optimization" was ~1.8× slower and read ~2× the bytes for both tool shares.

**Caveats.** With materialized columns for the filtered property, the second scan would be much cheaper and the trade-off could flip; not measured.

**Takeaway.** The scan (decompress + JSON-parse `properties`) dominates; the window sort it was meant to shrink is trivial by comparison. An IN-subquery over the same events table is a second full scan, so it roughly doubles the dominant cost for zero win. Don't pre-filter partitions of a window function when the filter requires re-scanning the same table you're windowing over.

Also learned while measuring: ClickHouse 26.x's **query condition cache** makes repeat runs of the same query read only the granules that matched last time (we saw 13.1M rows drop to 816 on run 2). Disable it with `use_query_condition_cache=0` when measuring, and don't credit it for production point-lookups whose predicate changes per request (e.g. per-session lookups); each new predicate is a cold run. And Metabase caches identical native queries entirely: add a changing comment/nonce per run or your "5 runs" are 1 run.

---

## 2026-06-10: Single-session lookups without a timestamp bound scan boundary granules across the team's whole history

**Context.** MCP analytics session-detail queries (`products/mcp_analytics/backend/logic.py` `_MCP_TOOL_CALLS_SQL`, `intent_generation.py` `_SESSION_INTENTS_SQL`): `WHERE event = 'mcp_tool_call' AND properties.$mcp_session_id = {sid}` with no timestamp predicate.

**Question.** How much does an unbounded single-session point lookup cost vs the same query bounded to 30 days, given `event` is in the sort key after `toDate(timestamp)`?

**Numbers.** Median of 5, Test Cluster, team 2 (history back to 2020, the event itself only present in a recent 5-day slice), `use_query_condition_cache=0`:

| Variant            | Duration (ms) | Read rows | Read bytes |
| ------------------ | ------------- | --------- | ---------- |
| no timestamp bound | 647           | 13.1M     | 3.11 GB    |
| `timestamp >=` 30d | 474           | 1.03M     | 2.90 GB    |

**Caveats.** The snapshot only held 5 days of this event, so both variants read the same event payload bytes; the 12M extra rows are sort-key boundary granules across ~6 years of partitions (index work + narrow columns, few bytes). In production the gap widens structurally: the unbounded query also re-reads the entire ever-growing event history's `properties` on every lookup.

**Takeaway.** Even when the `event` filter looks selective, with `toDate(timestamp)` unconstrained the primary index leaves ~1 boundary granule per (date, part) range, which adds up to millions of rows over years of partitions. Single-entity lookups (session, trace, etc.) should always carry a timestamp bound derived from how far back the entity can realistically be referenced.

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

---

## 2026-06-24: ClickHouse prunes unused `argMax(content)`; the real win is bounding the dedup, not dropping columns

**Context.** `products/signals/backend/temporal/signal_queries.py::fetch_source_products_for_reports` runs on every inbox report-list load (`signals.reports.list.fetch_source_products`, APM 7d p50 ~155ms / p95 ~1.4s). It deduped the team's whole signal history with `_deduped_signals_subquery()` (`argMax(content), argMax(metadata), argMax(timestamp) GROUP BY document_id` over `document_embeddings`) then filtered `report_id IN (<~25 page reports>)` on the OUTER query. `document_embeddings` is model-routed `ReplacingMergeTree`, `ORDER BY (team_id, toDate(timestamp), product, document_type, rendering, cityHash64(document_id))`, 3-month TTL; `report_id` lives in the `metadata` JSON, so nothing prunes — every load scans ~3 months of the team's signals.

**The proposed smell was partly wrong.** The hypothesis was "it `argMax`'s the big `content` string for every document, then throws it away." Measured against local synthetic single-team data (incompressible 3KB `content`), `read_bytes` for the original was **identical** to a variant that never selects content — ClickHouse's analyzer drops the `argMax(content)`/`argMax(timestamp)` because the outer query never references those aliases. Dead-column elimination already handled it; "drop the unused content argMax" buys ~0 at the ClickHouse layer.

**What actually costs.** The `argMax(metadata) GROUP BY document_id` over the _whole history_ — its hash table holds metadata per distinct document, so peak memory scales with the team's total signal count.

**Three shapes, local synthetic data (median of 5 from `system.query_log`), 360k rows / 360k docs, 600 reports, page = 25 reports:**

| Shape                                                                                                       | dur_ms | read_rows | read_bytes | peak_mem     |
| ----------------------------------------------------------------------------------------------------------- | ------ | --------- | ---------- | ------------ |
| CURRENT (dedup-all, filter after)                                                                           | 192    | 360k      | 39.5 MiB   | 174 MiB      |
| CANDIDATE (`document_id IN (SELECT DISTINCT ... WHERE report_id IN page)`, then argMax, filter still after) | 157    | 720k      | 76 MiB     | **14.3 MiB** |
| LEAN (single scan, `argMax(JSONExtract(...scalars))` instead of full metadata blob)                         | 309    | 360k      | 39.5 MiB   | 171 MiB      |

At 180k docs CURRENT peak*mem was 96 MiB; at 360k it was 174 MiB — memory grows ~linearly with team history. CANDIDATE went 2.6 MiB -> 14.3 MiB over the same doubling: bounded by signals in the \_displayed page's reports*, not the whole history. The wall-clock crossover (CANDIDATE faster) lands exactly on the signal-heavy teams that drive the p95 tail. CANDIDATE's cost is 2x metadata I/O (a second full-history `JSONExtract(report_id)` scan to build the candidate set) — cheap and parallel relative to the memory it saves. LEAN (drop the blob, argMax narrow scalars, single scan) was no better than CURRENT on memory at scale and noisier, so it was rejected.

**Correctness trap (same as the reverse-lookup sibling).** The `report_id IN (...)` filter must stay AFTER the `argMax`: a signal re-grouped from report A to B is matched by the candidate scan (it once carried A) but must be excluded because its _latest_ metadata points to B. Pushing the report_id predicate before the argMax would resurface the stale attribution. Verified identical results between all three shapes including the re-grouped case.

**Takeaway.** Before assuming a wide-column `argMax` is the cost, check whether the analyzer already prunes it (compare `read_bytes` against a content-free variant). When an `argMax ... GROUP BY high_cardinality_id` runs over a whole-history scan just to keep a small slice, bounding the group set with a `key IN (SELECT DISTINCT id WHERE <page predicate>)` prefilter trades a second (cheap, narrow) scan for an aggregation whose memory is bounded by the request page — the right lever for a memory/heavy-tenant-driven p95, even when it reads more bytes.

**Follow-up — the same shape where the wide column _is_ consumed (sibling `_signals_for_report_query`).** The neighbouring query dedups the whole history then filters to a single report, and its outer SELECT _keeps_ `content`, so the analyzer can't prune the `argMax(content)` — the original genuinely reads and buffers content for every document. Same candidate-bound fix, measured at 180k docs / 600 reports / one target report (~300 of its docs):

| Shape                              | dur_ms | read_rows | read_bytes | peak_mem   |
| ---------------------------------- | ------ | --------- | ---------- | ---------- |
| Original (dedup-all, filter after) | 583    | 180k      | 536 MiB    | 943 MiB    |
| Candidate-bounded                  | 88     | 210k      | **30 MiB** | **11 MiB** |

~18x fewer bytes, ~84x less memory, ~6.6x faster — far larger than the pruned-content case above, and on every axis (the extra DISTINCT scan reads only `document_id` + `metadata`, so total bytes still collapses because `content` is now read for one report's docs, not the team's). Lesson: the candidate-bound win scales with how much per-document data the post-filter throws away — biggest when the dedup buffers a wide column (`content`/`embedding`) that downstream actually needs.
