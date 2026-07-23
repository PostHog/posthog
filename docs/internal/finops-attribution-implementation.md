# FinOps attribution — implementation companion

Status: draft for discussion.
Companion to the [FinOps Attribution Pipeline RFC](https://github.com/PostHog/requests-for-comments-internal/pull/1210).

The RFC settles the _what_ (a unified `cost_attribution` table, a `finops.usage` envelope, vendor adapters) and the _why_.
It deliberately leaves the _how_ open — in the author's words, "it's very open atm".
This doc is the missing half: how the pipeline materialises in this repo, and — the part worth getting right up front — how emission is **standardised** so that Kafka consumers, Postgres access, Celery tasks, Temporal activities, ClickHouse queries and vendor bills all attribute cost the _same way_ instead of each team hand-rolling it.

It is a design sketch, not a build plan. File references point at the real chokepoints so the design stays honest.

---

## TL;DR — three decisions that make it standardised

1. **Attribution is ambient, not per-call-site.**
   Every place work happens in PostHog _already_ establishes an attribution context for ClickHouse query tagging — [`posthog/clickhouse/query_tagging.py`](../../posthog/clickhouse/query_tagging.py) sets `product` / `team_id` / `org_id` / `feature` on a `contextvar` at each entry point (HTTP middleware, Celery signals, Temporal, Dagster), and the Node ingestion pipeline threads `team` through every step's `PipelineContext`.
   The FinOps meter **reads that context**. A product engineer emitting usage supplies only what's genuinely new — the billable unit and the quantity — and inherits product/team/org for free. This is the single most important call: attribution correctness becomes the platform's job, done once at the chokepoint, not every caller's job done inconsistently.

2. **Two record types: usage meters vs. cost records.**
   The RFC's envelope mixes "a product consumed N units" with "this cost $X". Splitting them is what makes the success criterion (_sum of attributions == actual bill_) true **by construction**:
   - **Usage meters** are dimensionless counts emitted by products: "processed 1,000 recordings", "activity ran 4.2 CPU-seconds", "read 8 GiB from ClickHouse". No dollars. Cheap, high-volume, product-owned.
   - **Cost records** are dollars, produced by _one_ central **allocation job** that takes a known vendor total and splits it across usage meters by ratio. Products never write dollars, so a product can't make the books not balance; unallocated cost is just the residual the ratios didn't cover.

3. **One schema, three transports — chosen by source class, not by team.**
   Standardise the _schema and the dimension vocabulary_, then allow the cheapest transport per source: event push for live app usage, in-process metric aggregation for high-volume infra usage, and batch/derive for sources that already have good data (ClickHouse `query_log`, `$ai_generation` events, vendor bills). Every transport lands in the same `cost_attribution` table with the same dimension enums.

Everything below is these three decisions, spelled out.

---

## What already exists (reuse before building)

The fragmentation the RFC calls out is real, but so is a lot of reusable substrate. Cataloguing it keeps the build small.

| Capability                                                      | Where it lives today                                                                                                                                                                                    | Reuse as                                                           |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| Ambient attribution (product/feature/team/org) per unit of work | `posthog/clickhouse/query_tagging.py` (`QueryTags`, `tag_queries`, `Product`/`Feature` enums, `add_fallback_query_tags`)                                                                                | The attribution context the meter reads. Extend, don't replace.    |
| ClickHouse per-query usage (bytes/CPU/S3 ops)                   | `posthog/clickhouse/query_log_archive.py` (`read_bytes`, `memory_usage`, `ProfileEvents_*`); HogQL view `posthog/hogql/database/schema/query_log_archive.py`                                            | ClickHouse usage meter — **derive**, don't emit.                   |
| Per-request LLM cost, already priced per team/model             | `services/llm-gateway/.../callbacks/posthog.py` (`$ai_generation` w/ `$ai_total_cost_usd`, `team_id`, `ai_product`); ingestion-time `nodejs/src/ingestion/pipelines/ai/costs/index.ts`                  | AI cost record — **derive** from existing events.                  |
| Per-org usage rollup + billing delivery                         | `posthog/tasks/usage_report.py` (`OrgReport`, `UsageReportCounters`, `get_teams_with_*_in_period`, SQS to billing)                                                                                      | Per-org reporting shape and delivery path.                         |
| Dedicated ingestion pipeline precedent                          | AI events: `rust/capture/src/ai_endpoint.rs`, `AiSinkMode` in `rust/capture/src/config.rs`, `nodejs/src/ingestion/pipelines/ai/consumer.ts`, `posthog/models/ai_events/sql.py`                          | The blueprint for a `finops.usage` pipeline.                       |
| Staged, chart-toggled rollout of a dedicated endpoint           | `posthog/ph_client.py` (`enable_dedicated_ai_endpoint_for_default_client`), `DedicatedAIEndpointRollout` in `posthog/settings/ingestion.py`                                                             | Rollout mechanism for the new pipeline.                            |
| Scheduled third-party bill ingestion                            | `products/warehouse_sources/backend/.../sources/` (`SourceRegistry`; AWS CUR scaffold at `aws_cost_and_usage_report/source.py`, `FINANCE___ACCOUNTING` category; working Kubecost/Vantage/Brex sources) | Vendor-bill ingestion. AWS CUR is registered but unimplemented.    |
| "Define a cost model once, render to HogQL, expose per-team"    | `products/engineering_analytics/backend/logic/cost.py` + SPEC.md §5 managed `DataWarehouseSavedQuery` views                                                                                             | Template for exposing cost views without a global HogQL view.      |
| Per-org revenue for margin joins                                | `products/revenue_analytics/` (`revenue_item`, `customer.py`; keyed on Stripe `customer_id`)                                                                                                            | Revenue side of the margin join. Needs an identity bridge (below). |

**Genuinely greenfield** (grep confirms zero prior art): `cost_attribution` / `cogs` / `effective_cost` / `billed_cost` / `chargeback` vocabulary, the usage→cost allocation job, and the `team_id`/`org_id` ↔ Stripe `customer_id` identity bridge. The RFC's `transform_clickhouse_query_load()` does not exist yet either — but it can lean entirely on `query_tagging` + `query_log_archive` for its inputs.

---

## The standardisation model

### 1. Ambient attribution — harvest the context that already exists

`query_tagging.py` already solved "propagate who-is-this-work-for through arbitrary call stacks" for ClickHouse.
It's a `contextvars.ContextVar[QueryTags]` set at each entry point and reset on the way out:

- **HTTP** — `CHQueries.__call__` in `posthog/middleware.py` sets `kind="request"`, then view/auth code fills `team_id`/`org_id`/`product`; reset in `finally`.
- **Celery** — `prerun_signal_handler` / `postrun_signal_handler` in `posthog/celery.py:263` set `kind="celery"`, `id=task.name`; `reset_query_tags()` on postrun.
- **Temporal** — `update_query_tags_with_temporal_info` in `posthog/temporal/common/clickhouse.py:210` fills `TemporalTags` (workflow/activity type) lazily on first CH call.
- **Dagster** — `dagster_tags()` in `posthog/dags/common/common.py`, called per asset.
- **Node ingestion** — every pipeline step receives a `PipelineContext` carrying `team`; Kafka message headers carry the token that resolves to a team in `resolveTeam()`.

**The FinOps meter reads this, it does not reinvent it.** Concretely, model the attribution key on the existing `QueryTags` fields so the two systems share a vocabulary:

```python
# posthog/finops/context.py  (sketch)
@dataclass(frozen=True)
class Attribution:
    product: Product          # reuse query_tagging.Product — do NOT fork the enum
    team_id: int | None
    org_id: uuid.UUID | None
    feature: Feature | None
    environment: str          # prod-us | prod-eu | dev  (from settings)
    cost_type: CostType | None = None   # usually derived, see below

def current_attribution() -> Attribution:
    """Derive the ambient attribution from the query-tag context, applying the same
    add_fallback_query_tags() inference query tagging already uses."""
    tags = get_query_tags()
    return Attribution(
        product=tags.product,
        team_id=tags.team_id,
        org_id=tags.org_id,
        feature=tags.feature,
        environment=settings.FINOPS_ENVIRONMENT,
    )
```

Consequence: a Temporal activity that already runs under a workflow whose type maps to a product doesn't state its product when metering — it inherits it. When product is genuinely unknown, the record is written with `product=shared` / `allocation_method=residual`, which is exactly the RFC's "unallocated" bucket — and it's _loud_ (it shows up in the coverage view) rather than silently misattributed.

### 2. Usage meters vs. cost records

```text
                        emitted / derived                         central job
  ┌───────────────────┐   usage meters    ┌──────────────────┐   cost records   ┌────────────────────┐
  │ chokepoints &      │ ────────────────▶ │ usage_meters      │ ───────────────▶ │ cost_attribution   │
  │ vendor sources     │  (dimensionless    │ (quantity only)   │  (× unit price   │ (priced, balanced) │
  └───────────────────┘   quantities)      └──────────────────┘   from bills)     └────────────────────┘
```

A **usage meter** row answers "how much of billable unit X did product P consume for team T?".
It has `quantity` + `billable_unit` and _no_ dollars.

A **cost record** row answers "how many dollars of provider V's bill do we attribute to product P / team T?".
It is produced only by the allocation job, which distributes a _known_ provider total across usage meters. Because it distributes a known total, the sum is the total — the RFC's headline invariant holds automatically. `allocation_method` records _how_ (`direct`, `proxy_metric`, `volume_ratio`, `residual`) and `allocation_detail` records the ratio used.

This also makes ownership clean: **products own meters; finance/platform owns pricing.** A product team never needs to know what a CPU-second costs.

### 3. One schema, three transports

| Transport                  | For                                                                                         | Mechanism                                                          | Precedent                                                    |
| -------------------------- | ------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------ |
| **(a) Event push**         | Live app-layer usage, low/medium volume, needs per-org granularity                          | `finops.usage` events via a dedicated capture pipeline             | AI events pipeline (below)                                   |
| **(b) Metric aggregation** | High-volume infra usage (per Kafka message, per query) where one event per unit is too much | In-process per-key accumulator, flushed periodically to Kafka      | `TopHog` (`nodejs/src/ingestion/framework/tophog/tophog.ts`) |
| **(c) Batch / derive**     | Sources that already have good data                                                         | Scheduled Dagster adapter transforms existing data into the schema | `usage_report.py`, warehouse sources                         |

The **standard is the schema + the dimension enums**, not the transport. An "adapter" (RFC term) is concretely a registered function `(raw source) -> list[UsageMeter | CostRecord]`, mirroring the warehouse `SourceRegistry` and the AI `processCost` step.

---

## The standardised emitter SDK

Two thin libraries, one per runtime, same concepts and same wire schema.

### Python — `posthog/finops/`

```python
# the whole product-facing surface is this:
from posthog.finops import meter

# explicit unit + quantity; product/team/org inherited from ambient context
meter.record(billable_unit=BillableUnit.RECORDINGS, quantity=len(batch))

# time-based usage as a context manager (fills duration_ms, cpu if available)
with meter.measure(billable_unit=BillableUnit.COMPUTE, system="temporal"):
    do_expensive_work()
```

- `meter.record(...)` reads `current_attribution()`, stamps `environment`/`git_commit`/`service_name` (already available via `query_tagging.__get_constant_tags`), and hands the record to a transport.
- **Transport in web/API processes**: append to a request-scoped buffer, flush on the same boundary the query tags reset on (`CHQueries.__call__`'s `finally`). One capture call per request, not per meter.
- **Transport in Celery**: this is the classic footgun — `posthoganalytics.capture()` silently loses events in workers. Reuse the existing fix: `ph_scoped_capture()` (`posthog/ph_client.py`) already builds a dedicated client and flushes on exit. Flush FinOps meters in the same `postrun_signal_handler` where `reset_query_tags()` runs.
- **Chokepoint auto-instrumentation** (zero per-call-site code) is where standardisation pays off — one hook per entry point emits a baseline "this unit of work ran" meter for _everything_:
  - Celery: emit a `compute` meter with the task's wall time in `postrun_signal_handler` (`posthog/celery.py`), keyed by `id=task.name`.
  - Temporal: wrap `execute_activity` in `_PostHogClientActivityInboundInterceptor` (`posthog/temporal/common/posthog_client.py:63`) with a `try/finally` — `activity.info()` gives `workflow_type`/`activity_type` for the `workload` dimension. This is a better hook than the current lazy CH-only tagger because it fires even when the activity touches no ClickHouse.
  - Dagster: a global `run_status_sensor` (like `notify_slack_on_failure` in `posthog/dags/locations/shared.py`) emits a meter per run without per-asset opt-in.

### Node — `nodejs/src/common/finops/`

Model the meter on `TopHog`, which already solves per-team keyed aggregation flushed periodically to Kafka (so we don't emit one event per ingested message):

```ts
// registered once per consumer, threaded into step config like topHog already is
finops.record({
  billableUnit: 'events',
  quantity: batch.length,
  // product/team resolved from the pipeline context / message headers
  product: ctx.product ?? 'ingestion',
  teamId: ctx.team?.id,
})
```

- Flush path: `outputs.queueMessages(FINOPS_USAGE_OUTPUT, ...)` on the same 60s cadence `TopHog` uses — produces to a `finops_usage` Kafka topic. This is architecturally identical to `emitIngestionWarning` (`nodejs/src/ingestion/common/ingestion-warnings.ts`), which already does team-scoped JSON → Kafka → ClickHouse.
- **Chokepoint auto-instrumentation**:
  - Per-batch: `fetchAndDispatch` in `nodejs/src/common/kafka/consumer/consumer-v2.ts:300` already measures `consumedBatchDuration` around `eachBatch(messages)` and knows `topic`/`groupId`. Add the meter next to it.
  - Per-step: `StepPipeline.process` (`nodejs/src/ingestion/framework/step-pipeline.ts:26`) and `BaseChunkPipeline.next` already time each step via `pipelineStepDurationHistogram` with `step_name`; add a paired FinOps counter keyed the same way for step-level attribution.
  - Postgres: `postgresQuery` (`nodejs/src/common/utils/db/postgres.ts:254`) is the single wrapper every query passes through, already wrapped in `withSpan('postgres', ...)` with a `tag` call-site identifier — the natural per-query usage hook.

---

## Worked examples — the variety of cases

Deliberately spanning the RFC's "wide range of situations". Each shows what's ambient (inherited) vs. what the call site supplies, and which transport.

### A. Kafka consumer allocating usage (Node — the headline case)

**Chokepoint**: `fetchAndDispatch` in `consumer-v2.ts:300` (and the v1 twin). Every batch, every consumer (analytics, AI, replay, heatmaps, logs) passes through `await eachBatch(messages)` with `consumedBatchDuration`/`consumerBatchSize` already observed and `this.config.topic`/`groupId` in scope.

**Standardised emission** — one baseline meter per batch, aggregated by TopHog-style meter, keyed by `(topic, groupId)` and, where the batch is single-team, by `teamId`:

```text
usage_meter {
  billable_unit: "events"        # supplied (what this consumer meters)
  quantity:      messages.length # supplied
  system:        "warpstream"    # supplied (the Kafka vendor)
  workload:      groupId         # supplied (the consumer identity)
  product:       <from ctx>      # ambient — 'ingestion', or the per-message team's product
  team_id:       <from headers>  # ambient — resolved in resolveTeam()
  duration_ms:   <batch time>    # auto from consumedBatchDuration
}
```

Cost side: the Warpstream/MSK bill (a known monthly total, ingested as a vendor source) is split across these `events` meters by `quantity` → each consumer/team gets its ratio. `allocation_method="volume_ratio"`, `allocation_detail="topic=<t>,group=<g>"`.

Per-message team resolution matters for per-customer attribution: because `resolveTeam()` already lifts `team` into the pipeline context, a per-team meter is a `groupBy` on data the pipeline already has — no new plumbing.

### B. Node pipeline step (per-step compute attribution)

**Chokepoint**: `StepPipeline.process` / `BaseChunkPipeline.next`. `pipelineStepDurationHistogram` already labels by `step_name`/`step_type`. A sibling FinOps counter keyed identically turns "which step burned CPU" into a `compute` meter with `workload=<step_name>`, `product=<from ctx>`. Reuses the framework's existing `metrics.ts`; no step author writes anything.

### C. Postgres usage (Node + Django)

- **Node**: `postgresQuery` (`postgres.ts:254`) — every query carries a `tag` (call-site) and a `PostgresUse` (which physical pool). Emit a `db_query` meter keyed by `(tag, databaseUse)`; `withSpan` already gives duration. Team isn't in the signature today, so per-team Postgres cost starts as per-call-site and gets per-team only where callers thread `team_id` (acceptable — Postgres cost is mostly platform R&D, not COGS).
- **Django**: mirror via a DB instrumentation wrapper (Django's `connection.execute_wrapper`), emitting `db_query` meters under the ambient request/task attribution. RDS bill → split across `db_query` meters by time or rows.

### D. ClickHouse query cost (derive — do not emit)

No new emission. `query_log_archive` already has `read_bytes`, `memory_usage`, `ProfileEvents_OSCPUVirtualTimeMicroseconds`, S3 op counts, _and_ the `product`/`user_id` tags from `query_tagging`. A Dagster adapter (`transform_clickhouse_query_load()`, the RFC's named-but-unbuilt function) reads `query_log_archive` grouped by `(product, team_id)`, multiplies bytes/CPU by the ClickHouse-cluster unit cost derived from the AWS CUR + node bill, and writes cost records with `allocation_method="proxy_metric"`. **Gap to flag**: the HogQL view currently exposes `product` but not `team_id`/`org_id` — add them for per-customer ClickHouse cost.

### E. Temporal activity (Python — wall-clock attribution)

**Chokepoint**: `_PostHogClientActivityInboundInterceptor.execute_activity` (`posthog/temporal/common/posthog_client.py:63`). Wrap in `try/finally`, read `activity.info()` for `workflow_type`/`activity_type`, emit a `compute` meter with `workload=activity_type`, `system=<task queue>`, duration = measured wall time. Product inherited from the workflow-type→product map (extend the existing `TemporalTags` usage). Covers the RFC's "Temporal hooks" explicitly and fixes the current blind spot where attribution only exists if the activity happens to hit ClickHouse.

### F. Celery task (Python)

**Chokepoint**: `postrun_signal_handler` (`posthog/celery.py:263`). Task wall time is already computed there for metrics; emit a `compute` meter keyed by `id=task.name` right before `reset_query_tags()`. Flush via `ph_scoped_capture`. Zero per-task code.

### G. Dagster job self-cost (Python)

The cost-ingestion jobs themselves cost money to run. The same global `run_status_sensor` used for the auto-instrumentation meter (example in §Python SDK) attributes each Dagster run's compute to `product=data_platform`. Keeps the FinOps pipeline honest about its own overhead.

### H. AI / LLM cost (derive)

Already priced per team/model/product by the AI Gateway (`$ai_generation` with `$ai_total_cost_usd`, `team_id`, `ai_product`) and enriched at ingestion by `processCost`. The adapter reads these as **cost records directly** (`allocation_method="direct"`), then a reconciliation step compares the summed estimate against the actual Anthropic/OpenAI invoice and books the delta as a `residual` correction so the vendor total still balances.

### I. HTTP request (Django)

`CHQueries.__call__` (`posthog/middleware.py`) already has request wall time and the fully-resolved attribution in scope in its `finally`. Emit an `api_request` meter there for endpoints where request-level cost matters (Endpoints product already does query-cost via `EndpointsUsageQueryRunner`). Opt-in per route, not global, to avoid a meter per pageview.

### J. Vendor bills (warehouse sources + adapters)

Temporal Cloud, Warpstream, AWS CUR: implement as `SourceRegistry` sources under `products/warehouse_sources` in the `FINANCE___ACCOUNTING` category (AWS CUR is already scaffolded at `aws_cost_and_usage_report/source.py` — needs `source_for_pipeline`). Each vendor gets an adapter that normalises its bill into cost records / provider totals. Known associations (which cluster serves which product) live in versioned JSON alongside the adapter, exactly as the RFC proposes.

---

## The allocation job — how the books balance

One scheduled Dagster job, run per period, per provider:

1. Load the provider's **known total** for the period (from the vendor-bill source).
2. Load the relevant **usage meters** for the period (`usage_meters` table / ClickHouse-derived).
3. For each cost object, apply the allocation ladder, most-specific first:
   - `direct` — the bill line already names the product/team (e.g. AI Gateway per-request cost).
   - `proxy_metric` — split by a usage meter that correlates with cost (ClickHouse cost by `read_bytes`).
   - `volume_ratio` — split by raw quantity share (Kafka cost by message count).
   - `residual` — whatever's left, written as `product=shared`, `allocation_method=residual`. **This is the unallocated bucket, and it must exist** so totals reconcile.
4. Write priced rows into `cost_attribution`.

Invariant test (cheap, deterministic, worth a CI/backfill assertion): for every `(charge_date, provider)`, `sum(effective_cost_usd) == vendor_total`. If it doesn't, an adapter dropped or double-counted — fail loud.

Coverage over time = residual share trending down as more products emit meters. That's the RFC's coverage KPI, computed directly from `allocation_method`.

---

## Schema notes (refinements to the RFC's table)

The RFC's `cogs_attribution` DDL is a good starting point. Adjustments the implementation forces:

- **Name it `cost_attribution`.** The RFC already flags this; R&D and S&M rows don't fit "COGS".
- **Split usage from cost physically.** A `usage_meters` table (dimensionless, high-volume, product-written) feeding `cost_attribution` (priced, allocation-job-written). Keeps product writers off the priced table and lets meters have a shorter TTL than priced records.
- **Reuse the AI-events table shape** (`posthog/models/ai_events/sql.py`): Kafka-engine table → MV that `JSONExtract`s dimensions into typed columns → sharded `Distributed`/`ReplacingMergeTree`, with per-row `retention_days`/`drop_date`/TTL. This is the proven PostHog ingestion→CH pattern; don't invent a new one.
- **Dimension enums are shared code, not free strings** — see governance below. `product`, `cost_type`, `billable_unit`, `allocation_method` must be enums.
- **`environment` and `provider`** stay `LowCardinality(String)` as the RFC has them.
- The RFC's materialised views (`cost_by_product_daily`, `coverage_monthly`, `by_provider_monthly`, `paid_free_split`, `per_customer_monthly`) carry over unchanged — they read cleanly off the priced table.

---

## Enum governance & CI enforcement

The failure mode for a company-wide attribution schema is enum drift: `session_replay` vs `replay` vs `session-replay`, and the coverage view silently splits.
Per this repo's automation ladder (linter > lint-staged > skill > docs), lock it down mechanically:

- **`product`** — reuse the existing `Product` StrEnum in `query_tagging.py`. Do **not** fork it. It's already the canonical product taxonomy and already CI-adjacent (used in `assert_never` exhaustiveness).
- **New enums** (`BillableUnit`, `CostType`, `AllocationMethod`, `CostLayer`) — define once in `posthog/finops/`, generate the TypeScript/Node copy from the Python source (same OpenAPI/codegen path the repo uses for API types), so Node and Python can't diverge.
- **CI check** — a test that asserts every `product` written to `cost_attribution` is a valid `Product` member and every `finops.usage` event's `billable_unit` is a valid `BillableUnit`. Reject unknown values at ingestion (route to `residual`, count them) rather than accepting silent typos.
- **A skill** (`.agents/skills/adding-a-finops-meter/`) so adding a meter to a new subsystem is a scaffolded, consistent action — the same pattern the repo uses for warehouse sources and MCP tools.

---

## Rollout & phasing

Modeled on the AI pipeline's staged, chart-toggled rollout (`DedicatedAIEndpointRollout`), so nothing needs a deploy to advance.

- **Phase 0 — schema + derive-only.** Ship `cost_attribution` + `usage_meters` tables and the allocation job. Wire the three _derive_ adapters that need no new emission: ClickHouse (`query_log_archive`), AI (`$ai_generation`), and the first vendor bill (AWS CUR). This alone answers "what's our infra spend by product?" with zero product-team involvement — highest value, lowest coordination.
- **Phase 1 — standardised emitters + auto-instrumentation.** Ship `posthog/finops/` and `nodejs/src/common/finops/` with the chokepoint hooks (Celery, Temporal, Kafka batch, pipeline step). Every unit of work now emits a baseline compute meter automatically. `finops_usage` Kafka topic + dedicated consumer, mirroring the AI pipeline.
- **Phase 2 — per-customer + margins.** Populate `org_id` on app-layer meters, wire the revenue join (the `team_id`/`org_id` ↔ Stripe `customer_id` identity bridge is the real work here), light up `cost_per_customer_monthly` and margin views.
- **Phase 3 — first-class product.** Promote to `products/finops/` with its own scenes, reusing `engineering_analytics`' "cost model in Python → managed HogQL view" pattern for the UI surfaces.

---

## Open questions

- **Meter volume.** A baseline meter per Kafka batch is fine (TopHog-aggregated); a meter per _message_ is not. Where exactly is the aggregation grain per consumer? Default to `(topic, groupId, team_id, billable_unit)` per flush window.
- **Postgres per-team.** Worth threading `team_id` into `postgresQuery`'s signature for COGS-relevant tables, or accept per-call-site only? Most Postgres is platform R&D, so probably the latter.
- **Identity bridge.** Is there an existing `organization_id` ↔ Stripe `customer_id` map to reuse (`revenue_analytics_config.py` / `products/revenue_analytics/backend/joins.py`), or is a new mapping model needed?
- **Reconciliation cadence.** Vendor bills arrive days-to-weeks after usage. The allocation job needs to re-run for closed periods when a bill finalises — `ReplacingMergeTree` on `source_ingested_at` handles the overwrite, but the schedule needs to account for late-arriving totals.
- **dev environment.** Meters in local dev are noise. Gate emission on `environment != "dev"` (or a settings flag), same as `posthog-node` capture is gated on `POSTHOG_API_KEY`.
