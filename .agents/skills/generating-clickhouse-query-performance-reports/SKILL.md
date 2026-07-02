---
name: generating-clickhouse-query-performance-reports
description: >
  Produce and structure slow-query performance reports for PostHog's production
  ClickHouse (US and EU). Use when asked for a slow query report, query performance
  analysis over the last N days, per-team query cost, OOM or timeout investigation,
  cluster cost/memory regressions, or materialization candidates. Covers the modern
  `query_log_archive` source (typed `lc_*` columns, multi-day retention), how to
  categorize and attribute slow queries, root-cause patterns (unmaterialized
  JSONExtract, high-cardinality breakdowns, heavy joins), and the report structure.
  Runs queries via the `query-clickhouse-via-metabase` skill.
---

# Generating ClickHouse query performance reports

This skill is the _methodology_ for investigating slow ClickHouse queries and writing up a
performance report. It pairs with [`query-clickhouse-via-metabase`](../query-clickhouse-via-metabase/SKILL.md),
which is the _mechanism_ (SSO-gated auth and `hogli metabase:query`). Run every query in this skill
through that one.

Reports themselves are not public. When it exists, the private `PostHog/query-performance-analysis` repo
holds the historical reports and example query IDs; this repo holds only the tooling and methodology.
That repo is usually checked out as a **sibling folder** to the posthog checkout (e.g.
`../query-performance-analysis` relative to the repo root, or alongside it under the same parent
directory). Look for a sibling directory named `query-performance-analysis` containing an `analysis/`
folder of dated reports. If you find it, **add the new report there as a new markdown file** under
`analysis/`, named `<YYYY-MM-DD>-<topic>.md` (match the existing naming, e.g.
`2026-05-27-slow-queries-14d.md`).

**The sibling repo may not exist, and that is fine.** If you cannot find it, do not write into the public
posthog repo and do not block on it: write the report to a temp folder instead (e.g.
`/tmp/<YYYY-MM-DD>-<topic>.md`), tell the user where you put it, and skip the previous-report comparison
in step 9 (there is no history to diff against).

## Data source: `posthog.query_log_archive` (not `system.query_log`)

`system.query_log` on the production clusters retains only a few **hours**, so it cannot answer a
multi-day question. Use the Distributed archive table instead:

```sql
FROM posthog.query_log_archive
```

It retains roughly three weeks and exposes `log_comment` as typed columns, so you skip `JSONExtract`.
Query it directly (it already fans out across the cluster). Always filter `is_initial_query` so
distributed sub-queries are not double-counted. Confirm current retention with a per-day
`count()` before trusting a window (see `references/query-patterns.md`).

Key columns (full list via `system.columns WHERE table='query_log_archive'`):

| Column                                                                                    | Meaning                                                                                                                    |
| ----------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| `team_id` (Int64)                                                                         | Tenant. `0` / empty means internal or unattributed.                                                                        |
| `lc_kind`                                                                                 | How the query was issued: `request` (sync API/web), `celery` (async refresh), `temporal`, `cohort_calculation`, `dagster`. |
| `lc_product`                                                                              | `product_analytics`, `warehouse`, `experiments`, `messaging`, `web_analytics`, `replay`, `llm_analytics`, `cohorts`, ...   |
| `lc_access_method`                                                                        | `personal_api_key`, `oauth`, `sharing_token`, or empty (logged-in web).                                                    |
| `lc_query__kind`                                                                          | Product query type: `TrendsQuery`, `FunnelsQuery`, `RetentionQuery`, `HogQLQuery`, ...                                     |
| `lc_workload`                                                                             | `Workload.OFFLINE` / `ONLINE`.                                                                                             |
| `lc_feature`, `lc_temporal__workflow_type`, `lc_route_id`, `lc_api_key_label`             | Origin detail for attribution.                                                                                             |
| `lc_dashboard_id`, `lc_insight_id`, `lc_experiment_id`, `lc_cohort_id`                    | Link a query back to the object that triggered it.                                                                         |
| `query`, `query_duration_ms`, `read_bytes`, `read_rows`, `memory_usage`, `exception_code` | The query and its cost.                                                                                                    |

Both regions have the archive. US and EU are separate clusters with different workloads and
materialized columns; run cross-region comparisons against both. Discover the current ClickHouse
database id per region with `hogli metabase:databases` (ids are not stable). Note that the ONLINE and
OFFLINE Metabase connections for a region fan out to the same logical cluster, so they return the same
`query_log_archive` data.

## What counts as a slow query

```sql
query_duration_ms > 30000 OR exception_code IN (159, 160, 241)
```

| Code | Meaning               |
| ---- | --------------------- |
| 159  | TIMEOUT_EXCEEDED      |
| 160  | TOO_SLOW              |
| 241  | MEMORY_LIMIT_EXCEEDED |

Do **not** add `type = 'QueryFinish'`: OOM and timeout rows are `type = 'ExceptionWhileProcessing'`,
so that filter silently drops every failure. The duration/exception predicate already excludes
`QueryStart` rows (duration 0). Exclude the cluster health-poll query by `normalized_query_hash`
(pattern in `references/query-patterns.md`).

## Producing the report

The standard workflow, building from coarse to specific. Each step's SQL is in
`references/query-patterns.md`.

**Do not read previous reports until step 9.** Steps 1-8 should run against the raw data with fresh eyes,
so the analysis captures the largest surface area rather than re-walking last report's findings. Reading
the prior report early anchors you to its categories and makes it easy to miss a new problem it never
mentioned. Diff against history only after the independent pass is done.

1. **Confirm the window.** Per-day `count()` over the intended range to verify the archive actually
   covers it (retention can be shorter than you expect).
2. **Headline summary.** Total slow queries, total cluster query-hours, bytes read, teams touched,
   and the split across succeeded-but-slow / timeouts / OOMs / other. Also capture the **cluster-wide
   totals across all queries** (not just the slow set): total query-seconds, total CPU-seconds (typed
   `ProfileEvents_OSCPUVirtualTimeMicroseconds` column, not the `Map` lookup), total bytes read, and
   total OOMs (`references/query-patterns.md` §1b). The slow-set sums are a biased subset; the all-query
   totals are the honest "busier / reading more this period?" denominator and the baseline future reports
   diff against. They cannot be backfilled once a window ages past retention, so record them every run.
3. **Date distribution.** Slow count, timeouts, and OOMs per day. This is where incidents announce
   themselves: a multi-day OOM or timeout surge against a flat baseline.
4. **Categorize.** Group by `lc_kind` × `lc_product` × `lc_access_method`. This separates background
   work (data modeling, dagster pre-aggregation, batch exports) from synchronous user-facing queries.
5. **Attribute.** Drill into the worst categories by `team_id`. Rank by **total cluster-hours**
   (`sum(query_duration_ms)`) and by **OOM count** separately. Before calling anything systemic,
   check whether one team or one API key dominates a metric: a single integration querying via a
   `personal_api_key` can account for the large majority of cluster OOMs, and the "incident" is then
   really one tenant. Attribute by `team_id` + `lc_api_key_label` first. Then add a **top-consumers view
   over all queries** (not just the slow set): top teams, top API keys (`lc_api_key_label`), and top tools
   (`lc_product`) ranked by **bytes, CPU-seconds, and wall-time** (`references/query-patterns.md` §4c).
   This is where the heavy-but-fast consumers show up: a tenant or integration can dominate cluster CPU
   or bytes through millions of cheap queries while never crossing the slow threshold, so it is invisible
   to the slow-set ranking. The CPU:wall ratio per row separates compute-bound from wait/IO-bound load.
6. **Characterize user-facing slowness.** For `lc_kind='request' AND lc_product='product_analytics'`
   with empty `lc_access_method` (logged-in web), break down by `lc_query__kind` and flag
   `breakdown_value` usage and JSONExtract over `person_properties`. This is the product-actionable
   bucket. Always include the **JSON-extracted property breakdown** (`references/query-patterns.md` §7):
   the top event vs person property names pulled from JSON blobs in the slow set, and which teams use
   each. These are the materialization candidates and a required report output. `HogQLQuery` (arbitrary
   user- and AI-authored SQL) deserves its own deep dive, including how much is AI-written and why it is
   slow; see `references/hogql-deep-dive.md`.
7. **Root-cause the worst offenders.** For the top findings, do not stop at "team X is slow": pull the
   full query and form a hypothesis for _why_, then test it with EXPLAIN. Root-causing an individual
   query is the [`optimizing-clickhouse-and-hogql-queries`](../optimizing-clickhouse-and-hogql-queries/SKILL.md)
   skill's job; its [`references/investigation-playbook.md`](../optimizing-clickhouse-and-hogql-queries/references/investigation-playbook.md)
   is the playbook (pull the full query, bytes vs CPU vs duration, the runtime causes, origin tracing,
   EXPLAIN). A useful finding includes a why ("scans full history because the time filter is
   function-wrapped and can't prune granules"), even if stated as a hypothesis.
8. **Examples + write-up.** Capture `query_id` + `event_date` for the worst offenders in each finding,
   then write the report (structure below). Because `system.query_log` retention is short, examples are
   resolved from `query_log_archive` (`WHERE query_id = '…' AND event_date = '…'`), not the old Metabase
   lookup card. Link each example to a shareable self-contained Metabase URL (the `query_link` recipe in
   `references/query-patterns.md`) so a reader clicks straight through to the query. When you draft the
   recommendations, **ground the researchable ones in code** by spawning background research agents (see
   "Grounding recommendations in code" below) so a recommendation points at the actual file and change
   rather than saying "audit X".
9. **Diff against the previous report (do this last, if there is one).** If the sibling
   `query-performance-analysis` repo is not present, skip this step entirely. Otherwise, only now, after
   the independent pass above, read the most recent dated report in its `analysis/` folder
   (sort by filename date). Add a short **delta** section to the new report covering: what moved since
   last time (new incidents, findings that grew or resolved, headline numbers up or down), and a
   **follow-up check** on anything the previous report flagged as needing action (a materialization that
   was recommended, a team to watch, a pipeline to make incremental). For each prior follow-up, state
   whether it is resolved, still open, or regressed, with the current numbers as evidence. Doing this
   last is deliberate: it keeps the fresh analysis unbiased while still closing the loop on history.
   **Make the windows comparable before quoting a delta:** confirm the previous report used the same
   window length (both reports here use a trailing `now() - INTERVAL N DAY`, so equal length but with
   overlapping and partial edge days). Headline totals between two trailing windows are usually dominated
   by whichever one-off incident sits inside one window and not the other, so a large drop is rarely a
   structural improvement. Always also compare an **incident-excluded baseline** (e.g. OOMs/day with the
   spike days removed) so the delta is not misread, and say explicitly when a total moved because an
   incident aged into or out of the window. Remember the summed metrics (bytes read, cluster-hours) cover
   the **slow set only**, not total cluster I/O, so they also move when a heavy background job's runs
   cross or stop crossing the 30s threshold; attribute a big bytes/hours swing to specific categories
   (it is usually one or two background pipelines) rather than reporting it as a cluster-wide change.

## Grounding recommendations in code

A recommendation like "audit pipeline X" or "materialize property Y" is far more useful when it points at
the actual code. For each recommendation that maps to a concrete place in the PostHog codebase, **spawn a
background research agent** (the `Agent` tool, `run_in_background: true`, `subagent_type: general-purpose`
or `Explore`) to read the source and return: how the relevant code works today, the specific file /
function to change, any constraints, and whether a better mechanism already exists. Spawn **one agent per
researchable recommendation**, all in a single message so they run in parallel, as soon as the
recommendations are drafted. Let them run while you do the delta (step 9) and finalize the write-up, then
fold each finding into its recommendation: replace "audit X" with "X is implemented in `<file>` as
`<current behavior>`; the change is `<specific>`", and cite the file paths so the human can jump straight
in. The agents research and report only; they do not change code.

Not every recommendation is researchable this way. Spawn an agent only where source code is the source of
truth; skip operational / infra items:

| Recommendation shape                     | Researchable? | What the agent reads                                                     |
| ---------------------------------------- | ------------- | ------------------------------------------------------------------------ |
| Rewrite a slow insight / query shape     | yes           | the query runner under `posthog/hogql_queries/`, the HogQL it emits      |
| Materialize property X                   | yes           | the materialized-column registry (`ee/clickhouse/materialized_columns/`) |
| Make pipeline Y incremental              | yes           | the dagster / temporal job that builds it                                |
| Cap memory / add a query guard per key   | yes           | where ClickHouse SETTINGS and per-key throttling are applied             |
| Add a breakdown cardinality guard        | yes           | the trends / breakdown query runner                                      |
| Investigate an infra incident window     | no            | n/a (deploys, node health, cluster state)                                |
| Watch / confirm a tenant's intended load | no            | n/a (a judgement call for a human)                                       |

Give each agent a focused prompt: the recommendation, the specific question, and an instruction to return
file paths + current behavior + the precise change point and to change nothing. The agents read the
posthog repo (where this skill lives); the report itself is written to the separate
`query-performance-analysis` repo.

## Interpreting the results

- **Two populations live in "slow queries."** Tight-timeout API noise (queries erroring at ~10s
  against a low `max_execution_time`, usually `personal_api_key`) inflates the raw count without
  representing real compute. Genuinely expensive work is better measured by total cluster-hours and
  OOM count. Always call this distinction out; do not let timeout volume masquerade as slowness.
- **Bytes read is the truest cost signal**, more than duration (which varies with cache and cluster
  load). High bytes against low rows means heavy columns, almost always JSONExtract over a `properties`
  blob. For root-causing individual queries, see the
  [`optimizing-clickhouse-and-hogql-queries`](../optimizing-clickhouse-and-hogql-queries/SKILL.md) skill.
- **Background pipelines usually dominate raw cluster-time** (data-modeling DAGs, web-analytics
  pre-aggregation). That is expected; weigh them by whether their scan volume is necessary, separately
  from user-facing latency.

## Report structure

A report should contain, in order:

1. One-line scope: region, window, and the slow definition / exclusions used.
2. Headline numbers table + the **cluster-wide totals (all queries)** table (total query-seconds,
   CPU-seconds, bytes read, OOMs) + the two-populations caveat.
3. Daily distribution table (flag any incident window).
4. Findings, worst first. **Every finding needs at least one concrete `query_id` + `event_date`,
   linked via the shareable `query_link` URL** (see `references/query-patterns.md`) so a reader clicks
   straight through to the exact query, plus a **hypothesis for why it is slow** (from the
   [`optimizing-clickhouse-and-hogql-queries`](../optimizing-clickhouse-and-hogql-queries/SKILL.md)
   skill's investigation playbook). Group findings by what they are: a per-tenant incident, the
   heaviest cluster-time consumers, user-facing insight slowness, and tight-timeout API noise.
5. A **top-consumers-by-resource section** (all queries, not just slow): top teams, top API keys, and
   top tools (`lc_product`) ranked by bytes / CPU / wall-time (`references/query-patterns.md` §4c), calling
   out consumers that never trip the slow threshold and the compute-bound vs wait-bound split.
6. A **JSON-extracted property table**: the top event and person property names pulled from JSON blobs
   in the slow set, with the teams using each (`references/query-patterns.md` §7). These are the
   materialization candidates.
7. Concrete recommendations tied to each finding (materialize property X, cap memory per API key,
   make pipeline Y incremental, ...). Ground the researchable ones in code (see "Grounding
   recommendations in code"): cite the file / function and the specific change, not just "audit X".
8. A **delta vs the previous report** (step 9): what changed since last time, plus a follow-up check on
   each action the previous report recommended (resolved / still open / regressed, with numbers). Omit
   this section when there is no previous report.

Save the finished report as `analysis/<YYYY-MM-DD>-<topic>.md` in the sibling
`query-performance-analysis` repo, never in the public posthog repo; if that repo is not present, save to
a temp folder (e.g. `/tmp/<YYYY-MM-DD>-<topic>.md`) and tell the user the path.

## References

- `references/query-patterns.md`: ready-to-run SQL for every step above, against `query_log_archive`.
- `references/materialization-analysis.md`: finding properties to materialize and columns to drop,
  run across both US and EU.
- `references/hogql-deep-dive.md`: analyzing `HogQLQuery` (arbitrary user/AI SQL) specifically,
  including how to identify AI-written HogQL (`lc_product`/`lc_feature`, not `ai_query_source`) and the
  causes that make ad-hoc and AI queries slow.

## Related skills

This skill is fleet-level: it finds and ranks slow queries across all teams and writes the report. Once a
finding points at one query you want to explain or fix, switch to
[`optimizing-clickhouse-and-hogql-queries`](../optimizing-clickhouse-and-hogql-queries/SKILL.md) — it
owns root-causing an individual query (its `references/investigation-playbook.md`) and applying the fix at
the right layer (printer, query runner, or ClickHouse migration).
