# Marketing analytics — first-load performance spec

**Status:** Proposal / design spec (no code written yet)
**Area:** `products/marketing_analytics/` · owned by `team-web-analytics`
**Problem:** First load of the marketing analytics page is slow because the two heaviest
backend cost centers are recomputed from raw data inline, on the user's request thread,
on every cold load — and nothing warms the cache ahead of time.

---

## 1. Context and root cause

### 1.1 What loads on first paint

On mount the scene fires **4 query kinds in parallel** (frontend concurrency cap 6),
default range **last 7 days** (`marketingAnalyticsLogic.ts`):

| Tile | Query kind | Backend cost |
|------|-----------|--------------|
| Overview | `MarketingAnalyticsAggregatedQuery` | Ad-cost union + conversion-goal events scan |
| Trends chart | `InsightVizNode`/`TrendsQuery`, one `DataWarehouseNode` **per ad source** | N warehouse-table scans |
| Campaign breakdown | `MarketingAnalyticsTableQuery` | Ad-cost union + conversion-goal events scan (**rebuilt independently of Overview**) |
| Non-integrated conversions (only if goals exist) | `NonIntegratedConversionsTableQuery` | Events scan |

A single first load therefore runs the ad-cost union **at least twice** (overview + table,
each rebuilding the same `campaign_costs` CTE for the same range) and the conversion-goal
events scan **twice**, plus a per-source warehouse scan for the chart.

### 1.2 The two heavy cost centers

**A. Ad-cost union** — `marketing_analytics_base_query_runner.py::_build_campaign_cost_select`
+ `adapters/factory.py::build_union_query_ast`. `UNION ALL` across 1–10+ adapters
(Google / Meta / LinkedIn / TikTok / Bing / Reddit / Snapchat / Pinterest + BigQuery +
self-managed). Each adapter scans data-warehouse stats/entity tables with LEFT JOINs,
**inline `convertCurrency()` per row**, and — for Meta — **nested `JSONExtract`/`arrayFilter`
over the `actions` JSON column**. Rebuilt fresh per request; **no result caching, no
pre-aggregation.**

**B. Conversion-goal attribution** — `conversion_goal_processor.py`. Builds per-person arrays
of conversions + UTM pageviews from `events`, ARRAY JOINs them, attributes within the window.
Because the pageview filter extends the start back by `attribution_window_days` (default **90**;
`_build_pageview_event_filter`, lines 852–894), a "last 7 days" view scans **~97 days of
`$pageview` events.**

### 1.3 Why the existing precompute infra doesn't fix first load today

`conversion_goal_processor.py` already integrates the `analytics_platform`
**lazy-computation framework** (`ensure_precomputed`), with two ClickHouse tables that
**already exist in production**:

- `marketing_touchpoints_preaggregated` — config-agnostic UTM pageviews, shared across all
  goals/modes (one job per team). DDL: `posthog/clickhouse/preaggregation/marketing_touchpoints_sql.py`;
  migration `posthog/clickhouse/migrations/0271_marketing_touchpoints_preaggregated.py`.
- `conversion_goal_attributed_preaggregated` — pre-attributed conversion×touchpoint rows.
  DDL: `posthog/clickhouse/preaggregation/conversion_goal_attributed_sql.py`;
  migration `posthog/clickhouse/migrations/0261_conversion_goal_attributed_preaggregated.py`.

Three reasons it doesn't help first load:

1. **Flag defaults off.** `marketing_analytics_config.py:106-123` —
   `conversion_goal_precomputation_enabled` comes from the `marketing-analytics-precomputation`
   flag, default `False`. Most teams never hit the precompute path.
2. **Synchronous, read-time materialization.** The framework runs the heavy `INSERT…SELECT`
   **inline on the requesting thread** on a cold miss (README: *"we block an entire django
   thread"*). Even with the flag on, the *first* visitor after TTL expiry eats the full
   materialization + ~30% read-back overhead.
3. **No warming + cost union excluded.** Nothing schedules these jobs, and the **ad-cost union
   (cost center A) has no precompute path at all.**

### 1.4 The precedent

Web analytics already solved exactly this: `products/web_analytics/dags/web_dimensional_precompute.py`
defines `web_dimensional_precompute_job` + an **hourly schedule** that drives
`ensure_*_dimensional_precomputed` over a rolling 90-day window for a rollout audience, so user
queries hit a warm cache. Registered in `posthog/dags/locations/web_analytics.py`. Marketing
analytics has no equivalent.

---

## 2. Proposal P0 — Dagster warming job for the conversion-goal precompute tables

**Goal:** Move cost center B off the first-load critical path. A scheduled job materializes the
two existing preagg tables ahead of time so the user's first query is a cheap warm read instead
of a ~97-day cold `events` scan.

**No ClickHouse schema changes** — both tables already ship (migrations 0261, 0271). This is
purely a new Dagster job + schedule + flag enablement, reusing the existing read path.

### 2.1 New files

- `products/marketing_analytics/dags/__init__.py`
- `products/marketing_analytics/dags/marketing_precompute.py`
- `products/marketing_analytics/dags/tests/test_marketing_precompute.py`

### 2.2 Shape (mirror `web_dimensional_precompute.py`)

```python
# products/marketing_analytics/dags/marketing_precompute.py
import os
from datetime import UTC, datetime, timedelta

import dagster
import structlog

from posthog.cloud_utils import is_cloud
from posthog.dags.common import JobOwners
from posthog.models import Team
from products.web_analytics.dags.web_preaggregated import skip_on_kill_switch
from products.web_analytics.dags.web_preaggregated_utils import check_for_concurrent_runs

logger = structlog.get_logger(__name__)

PRECOMPUTE_WINDOW_DAYS = int(os.getenv("MARKETING_PRECOMPUTE_WINDOW_DAYS", "90"))
PRECOMPUTE_CHUNK_DAYS = int(os.getenv("MARKETING_PRECOMPUTE_CHUNK_DAYS", "1"))
DEFAULT_ROLLOUT_TEAM_IDS = [2]  # internal dogfood; tune for the v1 audience
SELECTED_TEAM_IDS_ENV_VAR = "MARKETING_PRECOMPUTE_TEAM_IDS"


def get_selected_team_ids() -> list[int]:
    raw = os.getenv(SELECTED_TEAM_IDS_ENV_VAR)
    if raw is None:
        return list(DEFAULT_ROLLOUT_TEAM_IDS) if is_cloud() else []
    return [int(p.strip()) for p in raw.split(",") if p.strip().isdigit()]
```

The op, per team, over a rolling window split into ≤`chunk_days` sub-windows (newest first):

1. **Touchpoints (shared, config-agnostic):** call `ensure_precomputed` with
   `build_touchpoints_precompute_query()` and
   `table=LazyComputationTable.MARKETING_TOUCHPOINTS_PREAGGREGATED`, window
   `[date_from - attribution_window, date_to]`, the same `ttl_seconds` dict the read path uses
   (`{"0d": 15*60, "1d": 60*60, "7d": 24*60*60, "default": 7*24*60*60}`).
2. **Attributed per goal:** for each team conversion goal eligible for precompute
   (`ConversionGoalProcessor._should_use_precompute`), call `ensure_precomputed` with
   `processor.get_attributed_query_for_precomputation()` and
   `table=LazyComputationTable.CONVERSION_GOAL_ATTRIBUTED_PREAGGREGATED`.

Reuse the existing builders in `conversion_goal_processor.py` — do **not** duplicate query
construction. The warming op should construct a `MarketingAnalyticsConfig.from_team(team)` and
`ConversionGoalProcessor` per goal exactly as the query runner does, then call the same
`ensure_precomputed` entry points (`_build_attributed_source_from_precompute` /
`_build_attribution_from_touchpoints_precompute` perform the ensure today; factor the
ensure-only half into a small reusable helper so both the read path and the dag call it).

Per-`(team, table, chunk)` failures must be caught and counted so one bad chunk doesn't poison
the rest. Emit Prometheus counters (`marketing_precompute_team_done_total{table}`,
`marketing_precompute_team_failed_total{table,error_type}`).

### 2.3 Job + schedule

```python
@dagster.job(
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value, "dagster/max_runtime": str(2 * 60 * 60)},
)
def marketing_precompute_job():
    ensure_marketing_precompute_op()

@dagster.schedule(
    cron_schedule="35 * * * *",        # hourly, offset from web's "20 * * * *"
    job=marketing_precompute_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
@skip_on_kill_switch
def marketing_precompute_schedule(context):
    skip = check_for_concurrent_runs(context)
    return skip or dagster.RunRequest()
```

### 2.4 Registration

`posthog/dags/locations/web_analytics.py` (marketing analytics is owned by team-web-analytics):
add `marketing_precompute` to the `from products...dags import (...)` block, append
`marketing_precompute.marketing_precompute_job` to `jobs=[...]` and
`marketing_precompute.marketing_precompute_schedule` to the `schedules` list. For local dev,
add the location to `.dagster_home/workspace.yaml` if not already covered.

### 2.5 Flag

Enable `marketing-analytics-precomputation` for the warmed teams (the read path keys off it via
`MarketingAnalyticsConfig.from_team`). The dag's team allowlist and the flag audience must be
kept in sync — warming a team that doesn't read precompute is wasted work; flagging a team the
dag doesn't warm reintroduces synchronous cold materialization. Recommend deriving both from the
same env-var allowlist initially.

### 2.6 Owner enum

No new owner needed — `JobOwners.TEAM_WEB_ANALYTICS` is correct
(`products/marketing_analytics/product.yaml` → `owners: [team-web-analytics]`).

### 2.7 Window/chunking rationale

- **90-day window** matches the default attribution window and `MAX_PRECOMPUTE_DAYS`, so any
  sub-range the UI requests (7/14/30/90d) is served from warm data.
- **1-day chunks** bound each `INSERT`'s scan; a cold backfill self-paces across runs (each
  re-run skips already-fresh windows). Newest-first so the short-TTL recent windows refresh first.

### 2.8 Testing

- Unit: `get_selected_team_ids` env-var/cloud/self-hosted matrix; `chunk_ranges`.
- Integration (`@pytest.mark.clickhouse`): seed events + a goal, run the op, assert rows land in
  both preagg tables and that a subsequent `MarketingAnalyticsTableQueryRunner` read is a warm
  hit (no fallback counter increment).
- Reuse the harness in `products/marketing_analytics/backend/hogql_queries/test_conversion_goal_precompute_e2e.py`.

### 2.9 Rollout

1. Land job behind empty default allowlist (no-op) + flag off → zero production impact.
2. Enable for internal team(s) via env var + flag; watch
   `lazy_computation_executions_total{cache_state}` and the fallback counter.
3. Expand the allowlist as warm-hit ratio and CH load look healthy.

### 2.10 Risks / mitigations

- **CH load from warming** → chunking + hourly cadence + `skip_on_kill_switch` +
  `check_for_concurrent_runs` (same guards web uses).
- **Allowlist/flag drift** → drive both from one source of truth.
- **Goals with person/cohort filters or remapped UTM schema** are ineligible
  (`_should_use_precompute`) and stay on the live path — the dag must skip them, not error.

---

## 3. Proposal P1 — Ad-cost rollup precompute (cost center A)

**Goal:** Remove the per-load rescan of external data-warehouse cost tables (the other half of
the latency, untouched by P0). Materialize a small daily-grain, currency-normalized cost rollup
that the overview, breakdown table, and trends chart read instead of re-unioning + re-converting
+ re-JSON-extracting the warehouse tables on every load.

**This one DOES require a new ClickHouse table + migration** (use the `/clickhouse-migrations`
skill). Net-new read path → larger review surface and the main reason P1 is riskier than P0.

### 3.1 New ClickHouse table (sketch)

`marketing_costs_daily_preaggregated`, populated via the lazy-computation manual API
(`LazyComputationTable.MARKETING_COSTS_DAILY_PREAGGREGATED`, new enum member), so it inherits
job tracking, TTL, and `(team_id, job_id, …)` ordering.

Grain: one row per `(source, campaign_id, campaign_name, ad_group_id, ad_group_name, ad_id,
ad_name, day)`.

```sql
CREATE TABLE sharded_marketing_costs_daily_preaggregated (
    team_id Int64,
    job_id UUID,
    day Date,
    source_name String,
    campaign_id String,
    campaign_name String,
    ad_group_id String,
    ad_group_name String,
    ad_id String,
    ad_name String,
    -- currency-normalized to team base currency at write time
    cost Float64,
    clicks Float64,
    impressions Float64,
    reported_conversions Float64,
    reported_conversion_value Float64,
    computed_at DateTime64(6, 'UTC') DEFAULT now(),
    expires_at Date DEFAULT today() + INTERVAL 7 DAY
) ENGINE = ReplacingMergeTree('marketing_costs_daily_preaggregated', ver='computed_at')
PARTITION BY toYYYYMMDD(expires_at)
ORDER BY (team_id, job_id, source_name, campaign_id, ad_group_id, ad_id, day)
TTL expires_at
SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1;
```

(Mirror the distributed/sharded pattern + `EXPIRY_BUFFER` handling used by the existing marketing
preagg DDLs.)

### 3.2 Write path

The `INSERT…SELECT` is the **existing adapter union**
(`MarketingSourceFactory.build_union_query_ast`) at **day grain**, with currency conversion and
Meta JSON extraction applied **once at write time** instead of per read. Time window via the
`{time_window_min}`/`{time_window_max}` placeholders. Warmed by the **same Dagster job as P0**
(add a third `ensure_precomputed` call per team).

### 3.3 Read-path changes

`_build_campaign_cost_select` gains a precompute branch (gated by a new flag, e.g.
`marketing-analytics-cost-precomputation`): when warm, build `campaign_costs` from the rollup
(filter `job_id IN (…) AND team_id = …`, `GROUP BY` the current drill-down dimensions, re-derive
rate metrics CPC/CTR/ROAS from summed totals) instead of from the adapter union. Fall back to the
live union on any miss — same pattern as the conversion-goal precompute.

The drill-down dimensions already map cleanly onto the rollup columns (campaign / source /
ad-group / ad; channel is derived from source; UTM levels don't use cost). Validate parity with a
test comparing live-union vs rollup results per level.

### 3.4 Bonus

The Trends chart currently fans out one `DataWarehouseNode` per source; it could instead read the
rollup, collapsing N warehouse scans into one preagg read. Out of scope for the first cut but
enabled by this table.

### 3.5 Risks

- **Currency correctness:** base-currency conversion must happen at write time and re-run if a
  team changes base currency (include base currency in the query hash so a change invalidates).
- **Parity:** rounding / rate-metric recomputation must match the live path exactly — gate behind
  a flag and ship a parity test (cf. `test_web_dimensional_precompute_parity.py`).
- **Schema migration** on a large cluster — follow `/clickhouse-migrations`.

---

## 4. Proposal P2 — Query-shape optimizations (no precompute required)

Independent, cheaper wins; can land before or alongside P0/P1.

1. **De-duplicate the per-page cost union.** Overview (`MarketingAnalyticsAggregatedQuery`) and
   breakdown (`MarketingAnalyticsTableQuery`) rebuild the same `campaign_costs` + conversion CTEs
   for the same date range on one page. Options: have the overview derive from the table's result
   client-side, or share a cached CTE/subquery server-side. Removes ~half the duplicated scan work
   on first paint.
2. **Revisit the 90-day default attribution window** (`MarketingAnalyticsConfig.attribution_window_days`).
   It sets the live fallback scan width (range + 90d). Confirm the default is intentional; a
   smaller default (or per-team tuning) materially shrinks the cold path that P0 doesn't cover.
3. **Cache per-request adapter discovery/validation + DW schema introspection.**
   `_get_marketing_source_adapters` + `MarketingSourceFactory` run fresh per request (validation
   runs once per adapter per page load). Partly mitigated by `prefetch_related` and the per-instance
   column cache, but the valid-adapter set could be memoized per `(team, source-config-version)`
   to cut Postgres round-trips on each tile.
4. **Avoid building conversion-goal CTEs for columns the request didn't select.**
   `_create_conversion_goal_processors` already skips unselected goals; verify the overview/table
   default column sets don't pull every goal when fewer are visible.

---

## 5. Proposal P3 — Storage / index tuning

Lowest leverage (precompute is where the wins are), listed for completeness.

- **Preagg ORDER BY already matches read filters** — `(team_id, job_id, person_id, …)` vs reads
  filtering `job_id IN (…) AND team_id = …`. No change needed.
- **External DW cost tables are date-partitioned** → date pushdown is already effective
  (`adapters/base.py::_get_where_conditions`). Limited index headroom on the source side.
- **Optional:** a `ReplacingMergeTree` projection on the P1 cost rollup for the common
  campaign/source grouping if read patterns warrant it.

---

## 6. Cross-cutting

### 6.1 Observability
- Existing: `CONVERSION_GOAL_PRECOMPUTE_FALLBACK_COUNTER` (`metrics.py`),
  `lazy_computation_executions_total{outcome,cache_state,table}`,
  `lazy_computation_jobs_{created,finished}_total`.
- Add per-table done/failed counters in the dag (§2.2). Watch warm-hit ratio
  (`cache_state="hit"` share) and the fallback counter as the rollout signal.
- Existing query telemetry: `marketing analytics query performed/failed` events
  (`marketing_analytics_base_query_runner.py::_capture_query_event`) carry `duration_ms` — use to
  measure before/after p50/p95 first-load latency.

### 6.2 Feature-flag strategy
- `marketing-analytics-precomputation` (exists) → P0 read path.
- `marketing-analytics-cost-precomputation` (new) → P1 read path.
- Keep dag allowlist and flag audiences in sync from one source of truth.

### 6.3 Recommended sequencing
1. **P2.1** (de-dup cost union) — cheap, immediate, no infra.
2. **P0** (warm conversion-goal precompute) — biggest single win, no schema change, clear precedent.
3. **P1** (cost rollup) — largest win on cost center A, but new CH table + parity work.
4. **P2.2–2.4, P3** — opportunistic.

### 6.4 Success metrics
- p50 / p95 first-load latency of `MarketingAnalyticsTableQuery` and
  `MarketingAnalyticsAggregatedQuery` (from the telemetry events) for warmed teams.
- Warm-hit ratio on the marketing preagg tables.
- Fallback-counter rate trending to ~0 for warmed teams.

---

## 7. Key file reference

| Concern | Path |
|---|---|
| Table query runner | `products/marketing_analytics/backend/hogql_queries/marketing_analytics_table_query_runner.py` |
| Aggregated/overview runner | `products/marketing_analytics/backend/hogql_queries/marketing_analytics_aggregated_query_runner.py` |
| Base runner (cost CTE, to_query) | `products/marketing_analytics/backend/hogql_queries/marketing_analytics_base_query_runner.py` |
| Conversion-goal processor (precompute paths) | `products/marketing_analytics/backend/hogql_queries/conversion_goal_processor.py` |
| Conversion-goal aggregator | `products/marketing_analytics/backend/hogql_queries/conversion_goals_aggregator.py` |
| Config + precompute flag | `products/marketing_analytics/backend/hogql_queries/marketing_analytics_config.py` |
| Constants / drill-down config | `products/marketing_analytics/backend/hogql_queries/constants.py` |
| Adapter factory / union | `products/marketing_analytics/backend/hogql_queries/adapters/factory.py` |
| Adapter base (DW scan, date pushdown) | `products/marketing_analytics/backend/hogql_queries/adapters/base.py` |
| Lazy-computation executor (`ensure_precomputed`) | `products/analytics_platform/backend/lazy_computation/lazy_computation_executor.py` |
| Lazy-computation README | `products/analytics_platform/backend/lazy_computation/README.md` |
| Touchpoints table DDL / migration | `posthog/clickhouse/preaggregation/marketing_touchpoints_sql.py` · `posthog/clickhouse/migrations/0271_marketing_touchpoints_preaggregated.py` |
| Attributed table DDL / migration | `posthog/clickhouse/preaggregation/conversion_goal_attributed_sql.py` · `posthog/clickhouse/migrations/0261_conversion_goal_attributed_preaggregated.py` |
| Dagster precedent (web) | `products/web_analytics/dags/web_dimensional_precompute.py` |
| Dagster location registration | `posthog/dags/locations/web_analytics.py` |
| Dagster owners enum | `posthog/dags/common/owners.py` |
| Frontend scene / load logic | `frontend/src/scenes/marketing-analytics/MarketingAnalyticsScene.tsx` · `.../tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic.ts` |
