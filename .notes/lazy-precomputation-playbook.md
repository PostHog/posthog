# Lazy precomputation playbook (web analytics)

How to add a new lazy-precomputation path for a web analytics tile, given what
we learned shipping paths-with-bounce (commit `adbbff02378`).

Target audience: a future session that wants to repeat the pattern for other
`WebStatsTableQuery` breakdowns (browser, OS, country, etc.) or for
`WebOverviewQuery`. This is the playbook to skim before starting — it
documents the non-obvious gotchas that cost the most debugging time.

---

## TL;DR — when to reach for this pattern

Use lazy precomputation when:

- The tile is read-heavy and a real bottleneck (events scan or session join is
  expensive).
- Data is mostly historical / settled — recent-data freshness can tolerate
  ~15 min staleness.
- The query has a stable "shape" (same SELECT/GROUP BY across users); per-user
  filters can be applied at readback over a dimensional cache.
- Live fallback is acceptable when the cache isn't warm or filters aren't
  supported.

Don't use it when:

- The tile is already fast enough on the live path.
- Per-user filters dominate (cache fragmentation makes it pointless).
- The query is hot AND already correct via `web_pre_aggregated_*` (Dagster
  preagg already covers that team).

---

## The pattern in 1 page

```
┌─────────────────────────────────────────────────────────────────┐
│ to_query() in the QueryRunner                                    │
│ ┌───────────────────────────────────────────────────────────┐    │
│ │ resolve_lazy_mode(runner) → mode | None                    │    │
│ │   - per-query override field on the query schema           │    │
│ │   - PostHog multivariate feature flag                      │    │
│ │   - eligibility guard (shape, recency, filter support)     │    │
│ └───────────────────────────────────────────────────────────┘    │
│                          │                                       │
│       ┌──────────────────┼──────────────────┐                    │
│       │ mode is not None │ mode is None     │                    │
│       ▼                  ▼                  ▼                    │
│  try:                 (skip)            existing Dagster /       │
│    get_lazy_strategy(  ↓                live dispatch            │
│      runner, mode                                                │
│    ).build_query()                                               │
│    set used_lazy = True                                          │
│  except NotReady:                                                │
│    fallthrough                                                   │
│  except ServerException:                                         │
│    log + fallthrough                                             │
│  # other exceptions PROPAGATE                                    │
└─────────────────────────────────────────────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│ build_query() in the LazyStrategy                                │
│   1. _ensure_precomputed() → list[str] job_ids                   │
│        - cap end at now() - 1h                                   │
│        - call ensure_precomputed(...) which:                     │
│            - hashes INSERT AST → query_hash                      │
│            - finds existing PG PreaggregationJob rows            │
│            - for missing daily windows, INSERTs to CH            │
│            - returns LazyComputationResult(ready, job_ids)       │
│        - if not ready: raise LazyPrecomputationNotReady          │
│   2. parse_select(<base query template>, placeholders=...)       │
│   3. _swap_<cached_part>(query, readback_subquery)               │
│        readback subquery filters by:                              │
│          team_id = X AND job_id IN (...) AND time_window_start   │
│          AND <dimension WHERE from WebAnalyticsPropertyTransformer>│
│   4. return finalized SelectQuery                                │
└─────────────────────────────────────────────────────────────────┘
```

---

## File layout (mirrors the bounce implementation)

For a new component named `<X>` (e.g. `browser`, `overview`):

| Path | Purpose | New file? |
|---|---|---|
| `posthog/clickhouse/preaggregation/web_analytics_<X>_<mode>_sql.py` | DDL per mode (sharded + distributed) | yes |
| `posthog/clickhouse/migrations/02NN_web_analytics_<X>_lazy_preaggregated.py` | Migration creating all mode tables | yes |
| `posthog/clickhouse/migrations/max_migration.txt` | Bump | edit |
| `posthog/clickhouse/schema.py` | Register sharded + distributed in test schema | edit |
| `posthog/hogql/database/schema/web_analytics_<X>_lazy.py` | HogQL Table class per mode | yes |
| `posthog/hogql/database/database.py` | Register HogQL tables in root | edit |
| `posthog/hogql/database/test/test_database.py` | Add to `test_no_new_posthog_tables` allow-list | edit |
| `posthog/hogql_queries/web_analytics/<X>_lazy_strategy.py` | Strategies + dispatch helpers | yes |
| `posthog/hogql_queries/web_analytics/<runner>.py` | `to_query()` dispatch + `used_lazy_precomputation` flag | edit |
| `posthog/hogql_queries/web_analytics/test/test_<X>_lazy.py` | Unit + parity tests | yes |
| `frontend/src/queries/schema/schema-general.ts` | Add per-query `<X>PrecomputationMode` field | edit |
| `posthog/schema.py` | Regenerated via `hogli build:schema` | edit (generated) |
| `frontend/src/queries/schema.json` | Regenerated | edit (generated) |
| `products/analytics_platform/backend/lazy_computation/lazy_computation_executor.py` | Add `LazyComputationTable` enum values | edit |

---

## HogQL gotchas (these cost the most time)

The lazy executor's `_build_manual_insert_sql` in
`products/analytics_platform/backend/lazy_computation/lazy_computation_executor.py:1020`
parses the INSERT template, prints to ClickHouse SQL, then iterates
`query.select` to build the INSERT column list. **Several invariants are easy
to miss.**

### 1. ALIAS EVERY SELECT COLUMN

`_build_manual_insert_sql` raises `ValueError("All SELECT expressions must be
aliased: …")` on any `ast.Field` (bare column ref). HogQL's `parse_select`
does NOT auto-wrap bare fields in `ast.Alias`.

**Wrong:**
```sql
SELECT toStartOfDay(start_timestamp) AS time_window_start, entry_pathname, host FROM ...
```

**Right:**
```sql
SELECT
    toStartOfDay(start_timestamp) AS time_window_start,
    entry_pathname AS entry_pathname,
    host AS host
FROM ...
```

Even `x AS x` is fine — what matters is that `query.select[i]` is `ast.Alias`,
not `ast.Field`.

### 2. HogQL function names ≠ ClickHouse function names

Many ClickHouse functions are NOT in HogQL's `HOGQL_CLICKHOUSE_FUNCTIONS` map
(`posthog/hogql/functions/clickhouse/conversions.py:20`):

| ClickHouse | HogQL |
|---|---|
| `toInt64OrZero(s)` | `toIntOrZero(s)` (input must be String, returns Int64) |
| `toUInt64(x)` | `_toUInt64(x)` (private/internal name; works in queries) |
| `toInt64(x)` | `_toInt64(x)` |
| `accurateCastOrNull(x, 'Int64')` | not exposed directly; `toInt(x)` maps to it but returns Nullable |
| `toUInt8(x)` | not in HogQL; use `_toUInt64(x)` for Bool→UInt8 promotion |

When in doubt: try parsing the template through `parse_select` + running
`prepare_and_print_ast` in a `__main__` script. Errors come back as
`QueryError: Unsupported function call 'X(...)'. Perhaps you meant 'Y(...)'?`.

### 3. Nullable ↔ non-nullable AggregateFunction columns

If your target column is `AggregateFunction(sum, UInt64)` (non-nullable),
writing `sumState(_toUInt64(nullable_value))` produces
`AggregateFunction(sum, Nullable(UInt64))` and ClickHouse rejects the INSERT
with `Conversion from AggregateFunction(sum, Nullable(UInt64)) to
AggregateFunction(sum, UInt64) is not supported`.

**Fix**: wrap inside `ifNull` BEFORE the cast.

```sql
sumState(_toUInt64(ifNull(is_bounce, 0))) AS bounces_count_state
```

Same applies to String columns — if the projection can be NULL, wrap with
`ifNull(any(...), '')`.

### 4. NULL filtering at INSERT vs readback

The live `avgIf(is_bounce, ...)` skips NULLs natively. Our cache doesn't unless
we filter at INSERT time. Mirror the live semantics:

```sql
GROUP BY events.session.session_id
HAVING any(events.session.`$is_bounce`) IS NOT NULL
```

---

## Lazy executor mechanics — what to know

`ensure_precomputed` (in
`products/analytics_platform/backend/lazy_computation/lazy_computation_executor.py`):

- **Synchronous, inline.** Blocks the Django request thread up to
  `DEFAULT_WAIT_TIMEOUT_SECONDS=180s` outer + `HOGQL_INCREASED_MAX_EXECUTION_TIME=600s`
  per CH attempt. With `max_retries=1`, worst case is ~20 min per cache miss.
- **Cache key**: SHA-256 of the INSERT's parsed AST `repr` + team timezone +
  breakdown fields. **Does NOT include HogQLQueryModifiers** — see Known
  Limitation #3 below.
- **PG job lifecycle**: missing windows → create PENDING jobs (partial unique
  index on `(team_id, query_hash, time_range_start, time_range_end) WHERE
  status='pending'`) → run INSERT inline → mark READY or FAILED. Failed jobs
  are excluded from `find_existing_jobs`, so repeated failures = repeated
  re-INSERTs (no native circuit breaker).
- **Exception swallow inside executor**: `_run_manual_insert` catches all
  exceptions, marks the job FAILED in PG, and returns
  `LazyComputationResult(ready=False, errors=[...])`. This means **the strategy
  layer's `except ServerException` won't see anything** — it only sees
  `ready=False`. The exception fingerprint lives in `errors` on the result.

### How to debug failed INSERTs

Look for `lazy_computation.job_failed` warning logs. The `error` field
contains the actual CH or HogQL error. Run pytest with `-s --log-cli-level=WARNING`
to surface them. Example:

```bash
flox activate -- bash -c \
  'hogli test posthog/hogql_queries/.../test_X.py -v -s --log-cli-level=WARNING 2>&1' \
  | grep "lazy_computation"
```

---

## Test patterns

### The silent-fallback trap (most important)

**Symptom**: parity tests pass even though the lazy path is completely broken.
**Cause**: lazy fails → executor returns `ready=False` → strategy raises
`LazyPrecomputationNotReady` → runner falls back to live. The parity test
compares "live result A" vs "live result B" — trivially equal.

**Fix**: add an assertion that the lazy path was actually taken.

```python
def _query(self, *, mode):
    ...
    runner = WebStatsTableQueryRunner(...)
    result = runner.calculate()
    result._used_lazy_precomputation = runner.used_lazy_precomputation
    return result

def test_lazy_matches_live(self, mode):
    live = self._query(mode=None)
    lazy = self._query(mode=mode)
    assert lazy._used_lazy_precomputation, f"mode={mode}: silent fallback"
    self._assert_parity(live.results, lazy.results)
```

### Test isolation

`APIBaseTest` reuses `team_id` across tests in the same class. PG
`PreaggregationJob` rows roll back per-test, but **ClickHouse rows persist**.
A second test with the same `query_hash` may find stale READY rows from a
prior test (if PG rollback didn't catch them) OR pollute the events table.

**Fix**: in parity-test `setUp`:

```python
from posthog.clickhouse.client import sync_execute
from products.analytics_platform.backend.models.preaggregation_job import PreaggregationJob

for table in ("sharded_web_analytics_X_dagster_shaped",
              "sharded_web_analytics_X_per_session",
              "sharded_web_analytics_X_narrow"):
    sync_execute(f"TRUNCATE TABLE IF EXISTS {table}")
PreaggregationJob.objects.filter(team=self.team).delete()
```

### Fixture coverage

Tests should cover the cases that silent-fallback hid in v1:

- Cross-midnight session (started Day D-1 23:55, events on Day D)
- Session with NULL `$is_bounce` (single pageview, very short duration)
- Session with NULL utm/geo properties
- Non-UTC team timezone (e.g. `US/Pacific`) with sessions near team-local midnight
- `includeHost=True` and `=False`
- `compareFilter` with explicit previous period
- Property filters that DO match a lazy-table column (e.g. `$device_type`)
- Property filters that DON'T match a lazy-table column — must fall through to live
- Path-cleaning rules toggled between runs

### Unit tests (cheap, fast)

Keep alongside the parity tests:

- Mode dispatch: each `WebAnalyticsBouncePrecomputationMode` value reaches the
  right strategy class and `LazyComputationTable` enum.
- Eligibility guard: `breakdownBy`, `includeAvgTimeOnPage`, `conversionGoal`,
  cohort filter, recent-range guard.
- Feature flag resolution: query override > flag variant > None; unknown
  variant logged but not crashing.
- Fallback on `ready=False`: monkeypatch `ensure_precomputed`, assert live
  runs and `tag_queries(...)` records the fallback.

---

## Known limitations carried forward (do these in your version)

Each is documented inline in `path_bounce_lazy_strategy.py`'s module docstring
with `KNOWN LIMITATION #N` grep markers. Address them before broadening rollout:

1. **Asymmetric 1h cap**: precomputation stops at `now() - 1h`, but readback
   uses `query_date_range.date_to()` (full range). For dashboards with
   `date_to ≈ now`, counts cover full range, bounce side covers less.
   Fix idea: clamp the readback period to `capped_to` too, surface the
   truncation in the response, OR reject queries whose `date_to` is too
   recent rather than serve a clipped bounce side.

2. **`STATS_TABLE_SUPPORTED_FILTERS` column mismatch**: dict includes property
   keys whose mapped column doesn't exist on the lazy table
   (`$browser_version`, `$os_version`, `$geoip_country_name`,
   `$geoip_time_zone`, `$channel_type`). Eligibility accepts them; readback
   fails with `UNKNOWN_IDENTIFIER`. Build a per-mode allow-list instead.

3. **Modifier ↔ cache mismatch**: `_build_manual_insert_sql` writes INSERTs
   under team-default modifiers; `compute_query_hash` doesn't include
   modifiers. Override `bounceRatePageViewMode` and the cache will return
   stale-semantics data for the TTL window. Requires changes to
   `_build_manual_insert_sql` AND `QueryInfo`/`compute_query_hash` —
   outside the strategy module.

4. **Synchronous INSERT, no circuit breaker**: degraded CH or large windows
   pin Django workers. Add a per-(team, query_hash) Redis breaker that
   suppresses lazy after K failures for M minutes.

5. **Wide sort key on dimensional table** (Option A): 25+ columns in ORDER BY.
   Trim to leading prefix + 1–2 breakdown columns once you pick a winning mode.

6. **Per-query override bypasses feature flag**: any authenticated user can
   force-trigger the lazy path for their team via the query field. Cost/DoS
   risk, not data leak. Gate to staff-only OR require both flag + query
   override to be on.

---

## Component-specific notes

### Other web stats breakdowns (browser, OS, country, …)

The PathBounceStrategy was a special case — it has a `LEFT JOIN bounce` that
the lazy code replaces. Other breakdowns use `MainQueryStrategy`
(stats_table_strategies.py:43) which is a single `SELECT ... FROM (inner)
GROUP BY breakdown_value`. No JOIN to swap.

For these, the lazy strategy needs to replace **the whole inner query** with
a readback, not just one half. Two options:

- **Mode A (dagster_shaped-like)**: cache stores aggregate states by all
  dimensions + breakdown. Readback selects `(visitors, views, bounce_rate)`
  with `*MergeIf` per period. Filter at readback via
  `WebAnalyticsPropertyTransformer`. Similar to existing
  `StatsTablePreAggregatedQueryBuilder._default_breakdown_query()`.
- **Mode C (filter_in_hash-like)**: cache stores `(breakdown_value, visitors_state,
  views_state)` per filter combo. Trivial readback. Bigger cache footprint
  if filters vary.

The `breakdown_value` differs by breakdown:
- BROWSER: `events.properties.$browser`
- OS: `events.properties.$os`
- COUNTRY: `events.properties.$geoip_country_code`
- VIEWPORT: `(viewport_width, viewport_height)` tuple — special case
- INITIAL_REFERRING_DOMAIN: `session.$entry_referring_domain`
- LANGUAGE: needs a special suffix (`-{country}`) per existing handler

Most non-PAGE breakdowns share the bounce-cache table (`web_pre_aggregated_bounces`)
in the Dagster preagg path, just selecting different dimensions. The lazy
version could share a single multi-purpose cache too — or one per breakdown.
The trade-off is between cache locality and storage cost; the existing
Dagster table is one giant shared cache. Probably want to match that.

### `WebOverviewQuery`

WebOverview is a different shape: one query, no breakdown, returns scalar
values (`visitors`, `views`, `bounce_rate`, `avg_session_duration`,
`unique_users`, etc.) plus their compare-period equivalents. Live path
is in `posthog/hogql_queries/web_analytics/web_overview.py`. Dagster preagg
already exists in `web_overview_pre_aggregated.py`.

For the lazy version:
- Cache table can be very narrow — no breakdown, just per-(team, time_window)
  aggregate states for the scalars.
- Inner subquery shape matches the bounce inner (session-aggregated). Reuse
  `_PER_SESSION_INNER_SQL` if possible.
- Readback returns a single row; the outer `WebOverviewQueryRunner` wraps it
  in the `WebOverviewQueryResponse` shape.
- Eligibility guard: same shape (no cohort filters, supported property
  filters only, no `conversionGoal`, recent-range guard).
- Filter pushdown: WebOverview uses `WEB_OVERVIEW_SUPPORTED_PROPERTIES` which
  is slightly different from `STATS_TABLE_SUPPORTED_FILTERS` (e.g. `$pathname`
  maps to `entry_pathname` for the overview). Use the right dict.

---

## Checklist for a new instance

Before opening a PR for a new component:

- [ ] Plan covers all 3 modes (or document why fewer)
- [ ] HogQL templates parse via `parse_select` in isolation
- [ ] Every SELECT column is aliased (search for bare `ast.Field` in `query.select`)
- [ ] All cast functions are in `HOGQL_CLICKHOUSE_FUNCTIONS` (or use the `_to*` private variants)
- [ ] Nullable values are `ifNull`-wrapped before going into `_toUInt64` / `_toInt64`
- [ ] HAVING filter excludes NULL-valued aggregates that should be skipped (mirror live `avgIf` etc.)
- [ ] HogQL Table schemas registered in `database.py` and `test_no_new_posthog_tables` allow-list
- [ ] CH tables registered in `posthog/clickhouse/schema.py`
- [ ] `LazyComputationTable` enum has new entries
- [ ] Migration uses `CREATE TABLE IF NOT EXISTS` (idempotent) and `node_roles=[NodeRole.DATA]`
- [ ] Per-query schema field defaults to `None`; multivariate feature flag drives team rollout
- [ ] `used_lazy_precomputation` flag plumbed through to `_calculate` so timezone is correctly disabled
- [ ] Catch-all narrowed to `ServerException` (programming errors propagate)
- [ ] Eligibility guard rejects unsupported filters AND cohort entries in `_test_account_filters`
- [ ] Test isolation: truncate CH tables + `PreaggregationJob` rows in parity test `setUp`
- [ ] Parity tests assert `_used_lazy_precomputation is True`
- [ ] Parity fixtures cover: cross-midnight sessions, NULL aggregates, non-UTC timezone, includeHost, compareFilter, supported + unsupported filters
- [ ] Known limitations documented inline with `KNOWN LIMITATION #N` markers + module docstring
- [ ] Run `hogli build:schema` after touching `schema-general.ts`

---

## Reference commit

`adbbff02378 feat(web-analytics): lazy precomputation for paths-with-bounce
(3 modes behind feature flag)`

17 files, +1976/-5. Includes module docstring with the full set of known
limitations. Read it before starting a new instance.

---

## Updates from PR #59665 (paths tile lazy precompute, May 2026)

Things we learned shipping the paths tile that aren't in the original playbook
above. Read this section before the next tile.

### Sharded tables go on `NodeRole.AUX`, not DATA

Match the `web_overview_preaggregated` convention (migration `0256`). The
distributed table targets `cluster=settings.CLICKHOUSE_AUX_CLUSTER`, so the
backing local table MUST live on AUX — otherwise envs where AUX != DATA have
no shards behind the distributed engine.

```python
operations = [
    run_sql_with_exceptions(
        SHARDED_..._TABLE_SQL(),
        node_roles=[NodeRole.AUX],
        sharded=True,
    ),
    run_sql_with_exceptions(
        DISTRIBUTED_..._TABLE_SQL(),
        node_roles=[NodeRole.DATA],
    ),
]
```

### Path cleaning belongs at READ time, not write time

Store raw `breakdown_value`. Apply `runner._apply_path_cleaning(...)` only in
the read SELECT/GROUP BY. Two wins:

1. The precompute is rule-independent: team rule edits don't invalidate stored
   rows.
2. The lazy_computation `query_hash` doesn't carry the regex literal.

Aggregate `*Merge` functions remain associative across the GROUP BY change.

### Move sort + pagination + fill-fraction into SQL

The first paths implementation read up to `READ_MAX_ROWS = 10000` ordered by
visitors DESC, then re-sorted in Python. For high-cardinality teams sorting
by anything other than visitors the cap truncates the real top-N. Codex P1.

Drop the cap; build the read template without `ORDER BY` / `LIMIT` / `OFFSET`,
then attach them to the parsed AST:

```python
parsed = parse_select(_READ_SQL_TEMPLATE, placeholders=placeholders)
parsed.order_by = _build_order_by(sort_column, sort_direction)
parsed.limit = ast.Constant(value=limit + 1)  # +1 for hasMore lookahead
parsed.offset = ast.Constant(value=offset)
```

For NULLS LAST regardless of direction, prepend `isNull(x) ASC`
(ClickHouse `OrderExpr` doesn't expose `NULLS LAST` directly):

```python
[
    ast.OrderExpr(expr=ast.Call(name="isNull", args=[ast.Field(chain=[col])]), order="ASC"),
    ast.OrderExpr(expr=ast.Field(chain=[col]), order=direction),
    ast.OrderExpr(expr=ast.Field(chain=["breakdown"]), order="ASC"),
]
```

Fill-fraction mirrors v2 (`stats_table_pre_aggregated.py:543`):
`visitors / sum(visitors) OVER ()` for count columns, passthrough for
bounce_rate.

### `avgMergeIf` returns NaN, not NULL — coerce in an outer SELECT

`ORDER BY ... NULLS LAST` won't catch NaN. Wrap with `if(isNaN(x), NULL, x)`
in an outer SELECT so the `isNull(x) ASC` ORDER BY prefix correctly places
no-entry-session rows at the end:

```sql
SELECT
    breakdown,
    if(isNaN(raw_bounce), NULL, raw_bounce) AS bounce_rate,
    ...
FROM (SELECT ..., avgMergeIf(state, <window>) AS raw_bounce FROM precompute GROUP BY breakdown)
```

### HogQL alias shadowing — pick a distinct SELECT alias

If a SELECT projects `cleaning_fn(col) AS col` (alias matches the underlying
column), HogQL resolves subsequent references in GROUP BY to the SELECT alias
and prints the GROUP BY expression WITHOUT the table qualifier. ClickHouse
then rejects with "not under aggregate function and not in GROUP BY keys".

Workaround: pick a different alias (e.g., `breakdown` not `breakdown_value`).
Consumers should destructure positionally.

### INITIAL_PAGE reuses the same precompute table

Feed `_entry_breakdown_value_expr` into BOTH `breakdown_value_expr` and
`entry_breakdown_value_expr`. Effects:

- Inner `GROUP BY (session_id, breakdown_value)` collapses to per-session
  (entry pathname is fixed within a session).
- Outer aggregate is "sessions that entered on this path" — matches v2's
  INITIAL_PAGE semantic.
- `equals(breakdown_value, entry_breakdown_value)` is always true → bounce
  contributes for every row.
- The AST differs from PAGE, so the `query_hash` differs and the two
  breakdowns coexist as distinct precompute jobs.

Add a defence test that asserts the cache-key hashes don't overlap — a
future refactor that collapses the two expressions would silently corrupt the
entry-path bounce numbers.

### Frontend opt-in toggle lives in the createTableTab base, NOT per-tab

`useWebAnalyticsPrecompute` MUST go into the `createTableTab` base
WebStatsTableQuery source. Otherwise tabs that forget to pass it (Entry path,
End path, channel breakdowns, frustrating-pages, …) arrive at the backend
without the opt-in and get rejected with `PerQueryOptInNotSet` even when the
team toggle is on.

```typescript
source: {
    kind: NodeKind.WebStatsTableQuery,
    ...
    useWebAnalyticsPrecompute,  // ← in the BASE
    ...source,                  // ← per-tab overrides last
}
```

### CI-only flake family for round-trip parity tests

Any test of the shape `with _enable_lazy(): _run(query)` followed by metric
assertions on the lazy result is in the #59075 CI-only flake family — passes
locally on the same ClickHouse image used by CI, flakes on CI with empty
lazy results despite READY jobs. Until the underlying read-after-write
visibility issue lands, skip defensively:

```python
@unittest.skip(
    "CI-only flake since #59075 (passes locally on the CI ClickHouse image) — "
    "<short reason>. Re-enable when the read-after-write visibility issue is resolved."
)
```

For parameterized tests, place skip BELOW `@parameterized.expand` (per
#59695 lesson) or use `self.skipTest(...)` in the body (with
`# type: ignore[unreachable]` on the first line after).

### Stamphog gates auto-deny CH-migration + size PRs

Stamphog won't approve any PR that touches a CH migration or exceeds the
size/complexity threshold, even when substantive bot concerns are addressed.
The gate is structural. Plan on a human reviewer for any sizable lazy
precompute PR.

### Deferred (next picks)

- `avg_time_on_page` — raw path uses `quantile(0.90)` per-pageview; lazy
  INSERT today groups per-session-path. Adding it cleanly requires a
  UNION/JOIN-of-two-subqueries shape mirroring `PATH_BOUNCE_AND_AVG_TIME_QUERY`
  in `query_constants/stats_table_queries.py`.
- DRY refactor between `web_overview_lazy_precompute.py` and
  `web_stats_paths_lazy_precompute.py` — placeholders factory + generic
  `execute_lazy_orchestrator` in `web_lazy_precompute_common.py`. Defer until
  a third tile lands.

### Reference commits (PR #59665)

- `dd70de35a4d` — AUX cluster migration fix + mypy unreachable silencers
- `2414f9fca20` — SQL sort + pagination + fill-fraction (drops READ_MAX_ROWS)
- `62fe6b57554` — Path cleaning at READ time
- `1c1e5cf729a` — INITIAL_PAGE breakdown support
- `a0c0bf83d90` — Frontend `useWebAnalyticsPrecompute` in createTableTab base
