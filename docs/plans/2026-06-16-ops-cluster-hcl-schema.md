# Migrate the OPS (then LOGS) ClickHouse cluster to declarative HCL schema

> On execution, relocate this plan to `docs/plans/2026-06-16-ops-cluster-hcl-schema.md` (repo convention). It lives here only because plan mode restricts edits to this file.

## Context

PostHog's satellite ClickHouse clusters (OPS, LOGS, …) are currently defined by sequential Python migrations under `posthog/clickhouse/migrations/` plus SQL generators (e.g. `posthog/clickhouse/query_log_archive.py`) and registered in `posthog/clickhouse/schema.py` tuples for local creation. The real clusters have drifted **far** from the repo: production/dev hold many objects the repo never defines (metrics suites, tophog, prom_metrics, legacy `query_log_archive_old`, `custom_metrics*` views). The repo is no longer a faithful source of truth.

A sibling Go tool, `hclexp` (in `../python-clickhouse-schema`), manages ClickHouse schemas declaratively in HCL: introspect/dump a live cluster to HCL, layer base + per-env overrides, resolve to a flat desired state, `validate` references, `diff -sql` to emit migration DDL, and `drift` to guard cross-node consistency. Per-node production/dev dumps already exist in `../clickhouse-schema/{dev,prod-us,prod-eu}/*-ops.hcl` (flat full dumps, with `node{}` macro blocks).

**Goal:** make HCL the source of truth for these clusters, in the posthog repo, driving **both prod and local**, reconciling the repo with reality. **Start with OPS** because its materialized view is created on _every_ node role and writes into the OPS-only data table — a cross-cluster dependency that must be modeled first. LOGS follows using the same scaffolding.

### Decisions (confirmed with user)

- End state: **HCL source-of-truth AND repo reconciliation** (capture prod-only objects into HCL).
- Location: **in the posthog repo**.
- Scope: HCL drives **OPS and LOGS, prod + local**; OPS first.
- `hclexp` delivery: **prebuilt container image** (`ghcr.io/posthog/chschema*`), pinned by tag, invoked in CI and via a local wrapper.
- Local target: **both** the default single-node dev and the multinode `clickhouse-ops` node.

## Key findings (the shape of OPS)

**Cross-cluster fan-in (model this first).** Only `sharded_query_log_archive` (ReplicatedMergeTree, single-shard) physically lives on OPS. Every node role (DATA, ENDPOINTS, INGESTION\_\*, LOGS, AUX, AI_EVENTS, SESSIONS, OPS) also gets three Distributed/MV objects that all reference the OPS data table:

- `query_log_archive` — Distributed **read** → `ops.sharded_query_log_archive`
- `writable_query_log_archive` — Distributed **write** → `ops.sharded_query_log_archive`
- `ops_query_log_archive_mv` — MV reading each node's local `system.query_log` (`type != 'QueryStart'`), extracting `team_id` from the `log_comment` JSON, normalizing `log_comment`, and writing to `writable_query_log_archive`.

Repo source: `posthog/clickhouse/query_log_archive.py` (`SHARDED_QUERY_LOG_ARCHIVE_OPS_TABLE_SQL`, `DISTRIBUTED_…`, `WRITABLE_…`, `QUERY_LOG_ARCHIVE_OPS_MV_SQL`), registered in `schema.py` tuples; created by migrations `0273_query_log_archive_ops_json.py` / `0274_fix_query_log_archive_log_comment_mv.py`. The modern schema is JSON-backed: physical `log_comment` (JSON) + `ProfileEvents` (Map) with ~58 `lc_*` and ~17 `ProfileEvents_*` read-time aliases.

**Objects in the dumps but NOT in the repo (reconciliation targets):**

- Shared/all-env: `custom_metrics*` views (~9), `daily_aggregated_query_log_archive` view.
- dev only: `prom_metrics` (TimeSeries) + `prom_metrics_data/_metrics/_tags` + `writable_prom_metrics*` (Buffer).
- prod-us + prod-eu: `metrics_*` suite (`metrics_samples`, `metrics_series`, `metrics_exemplars`, `metrics_histograms`, `metrics_label_index`, `metrics_metadata` + `metrics_label_index_from_series_mv`), `sharded_tophog` (TTL 30d).
- prod-us only: `events_main`, `events_recent` (Distributed proxies to the main cluster).
- prod-eu only: `events_team_daily_stats` (also in dev), `query_log_archive_old` (legacy, awaiting manual backfill — `backfill_sharded_query_log_archive.sql` at repo root).

OPS is single-shard replicated (`SINGLE_SHARD_DATA_NODE_ROLES`); local cluster name `ops`, db `posthog`. 1a/1b (or 1c/1d) nodes differ only by `{replica}` macro.

**Ownership caveat:** `metrics_*`, `prom_metrics`, `sharded_tophog`, `custom_metrics*` look like infra/observability-owned, not posthog-app-owned. During execution, confirm ownership per object and either author it into the repo HCL (app-owned) or capture it as `external`/`raw` and exclude from app-managed diffs (infra-owned). Do not assume the app should start managing infra tables.

**Local topology.** `docker-compose.multinode-clickhouse.yml` boots one CH server per role incl. `clickhouse-ops` (macros `shard=01, replica=ops, hostClusterRole=ops`; `remote_servers` define `ops`, `posthog`, `posthog_single_shard`, …). Default `./bin/start` is single-node (OPS collapses onto the main server). Migrations run via `manage.py migrate_clickhouse`; `manage.py print_ch_migration_sql` renders desired-state DDL **without** a cluster connection (useful for cross-checking HCL output). `hclexp`/`chschema`/`.hcl` are not yet referenced in the repo.

**hclexp constraints to verify against the pinned tag:** plain `view` and `dictionary` top-level blocks are listed as "planned, not implemented" in CLAUDE.md, yet the dumps contain `view` blocks — confirm whether views round-trip natively or must be captured as `raw{}`. `raw{}` table changes are flagged `-- UNSAFE`. TimeSeries engine is experimental.

## Approach — OPS first (phased)

### Phase 0 — Tooling & scaffolding

1. Pin an `hclexp` image tag. Add a thin local wrapper (justfile/hogli target, e.g. `hogli ch:hcl ...`) that runs `docker run --rm -v $PWD:/work ghcr.io/posthog/chschema:<tag> <args>` and an `-ops` variant where git/sh are needed.
2. Create the HCL tree in the repo:

   ```text
   posthog/clickhouse/hcl/
     base/ops.hcl          # shared OPS objects (query_log_archive trio + MV; app-owned shared views)
     env/dev.hcl           # prom_metrics + events_team_daily_stats
     env/prod-us.hcl       # metrics_* suite, sharded_tophog, events_main/recent
     env/prod-eu.hcl       # metrics_* suite, sharded_tophog, events_team_daily_stats, query_log_archive_old (transitional)
   ```

   `database "posthog" { cluster = "ops" ... }` so the cluster default cascades. Per-node `{shard}`/`{replica}` stay as macros (never hardcoded), so 1a/1b collapse to one definition.

### Phase 1 — Author the layered OPS source-of-truth (no operational change)

3. Seed `base/ops.hcl` from a prod-us ops node dump (`../clickhouse-schema/prod-us/prod-us-iad-ch-1c-ops.hcl`): strip the `node{}` block, keep the shared `query_log_archive` trio + `ops_query_log_archive_mv`. Factor the shared physical columns of the three query_log_archive objects into an `abstract` base table + `extend` to remove duplication. Move env-only objects into `env/*.hcl` (use `patch_table` for per-env column additions, full blocks for per-env tables). Capture app-owned views; capture infra-owned/unsupported objects as `raw{}` or `external` named collections, or exclude — per the ownership decision above.
4. Prove fidelity: for each env, `hclexp diff -left posthog/clickhouse/hcl/base,posthog/clickhouse/hcl/env/<env> -right <that env's committed ops dump>` must report **zero drift** (or only intentionally-excluded infra objects). Iterate the HCL until clean. Run `hclexp validate` so the MV source/destination and Distributed remote references all resolve.
5. Vendor the per-env OPS golden dumps into the repo (or add `../clickhouse-schema` as a pinned reference) so CI has a deterministic diff target without live-cluster creds.

### Phase 2 — CI guards

6. Add a CI job (image-based, no Go toolchain) that on every PR touching `posthog/clickhouse/hcl/**`:
   - `hclexp validate` the resolved layers (references resolve);
   - `hclexp diff` resolved-layers vs each vendored golden dump → fail on unintended drift;
   - render `hclexp diff -sql` into the PR (like `print_ch_migration_sql`) and **flag any `-- UNSAFE`** so destructive DDL is reviewed, never auto-applied.
     Add a separate scheduled/manual job that diffs the layered HCL against the **live** clusters (with read-only creds) for true drift detection — out of PR critical path.

### Phase 3 — Local creation from HCL (both targets)

7. Add a local apply path: `hclexp diff -left base,env/dev -right clickhouse://<host:port>/<db> -sql` then pipe DDL to the local server — `clickhouse-ops` (multinode) and the main server (single-node, where OPS == main). Wrap as a hogli/just target and wire into dev bootstrap so OPS tables are created from HCL.
8. Once HCL creates OPS tables locally, remove the OPS entries from `schema.py` tuples to avoid double-creation, **keeping the "no table only in cloud" guarantee satisfied via the HCL path** (update the CI scoping/no-cloud-only check to recognize HCL-managed tables, or keep a thin shim). Verify `setup_test_environment.py` / `conftest.py` test-DB build still yields all OPS tables.

### Phase 4 — Cut over schema evolution

9. New OPS schema changes flow through HCL: edit the HCL, `hclexp diff -sql` (reviewed, `-- UNSAFE`-gated), apply operationally. Stop writing new Python migrations for OPS DDL. Existing historical OPS migrations remain as applied state (do not delete). The Python `query_log_archive.py` generators can be retired once nothing imports them at runtime (some query runners may still reference table names — verify before removing).

## Reconciliation strategy for prod-only objects

- App-owned (e.g. anything the posthog codebase reads/writes): author full HCL blocks in the right env layer; this is the "repo reconciliation" deliverable.
- Infra/observability-owned (`metrics_*`, `prom_metrics`, `sharded_tophog`, `custom_metrics*` if owned elsewhere): capture as `raw{}`/`external` for completeness OR explicitly exclude from app-managed diffs, documented in `base/ops.hcl`. Decide per object during Phase 1; do not silently start managing infra tables.
- `query_log_archive_old` (prod-eu): model as a transitional `raw{}`/table block flagged for removal post-backfill; never let an apply drop it automatically.

## LOGS follow-on (after OPS lands)

Reuse the same `base/ + env/` scaffolding and CI/local wiring for LOGS. LOGS has a larger reconciliation gap: repo defines `logs32`/`log_attributes`/`logs_kafka_metrics` (+ Kafka tables only in `bin/clickhouse-logs.sql`), while dumps have `logs34`/`log_attributes2` plus `metrics*`, `trace_spans*`, `trace_attributes*`, `logs_billing_metrics*`. Note prod-us has a trace kafka-metrics table/MV that prod-eu lacks, and dev has no traces/metrics — natural env layers. Local multinode currently has no `clickhouse-logs` node; adding one is a prerequisite for local LOGS.

## Critical files

- New: `posthog/clickhouse/hcl/{base/ops.hcl,env/dev.hcl,env/prod-us.hcl,env/prod-eu.hcl}`; local/CI wrapper (justfile/hogli target); new CI workflow under `.github/workflows/`.
- Reference (source of truth for authoring/diff): `../clickhouse-schema/{dev,prod-us,prod-eu}/*-ops.hcl`; `../python-clickhouse-schema` (docs/README.hcl.md, FAQ.md).
- Reconcile against: `posthog/clickhouse/query_log_archive.py`, `posthog/clickhouse/schema.py`, `posthog/clickhouse/migrations/0273_*.py`, `0274_*.py`, `backfill_sharded_query_log_archive.sql`.
- Touch in later phases: `schema.py` tuples, dev bootstrap (`bin/`), the no-cloud-only-table CI guard, `docker-compose.multinode-clickhouse.yml` (LOGS phase).

## Verification

1. **Fidelity:** `hclexp validate` clean; `hclexp diff` of resolved layers vs each committed dev/prod-us/prod-eu ops dump reports zero unintended drift.
2. **Local apply (single-node):** fresh `./bin/start` → run the HCL apply target → `hclexp introspect` the local db → `hclexp diff` vs `base,env/dev` is empty; confirm OPS tables exist and `ops_query_log_archive_mv` copies rows from `system.query_log` into `sharded_query_log_archive`.
3. **Local apply (multinode):** bring up `docker-compose.multinode-clickhouse.yml`, apply to `clickhouse-ops`, repeat introspect/diff; verify the Distributed `query_log_archive` on a non-ops node reads through to the ops data table.
4. **Test suite:** `setup_test_environment` builds all OPS tables; existing CH migration tests (`hogli test posthog/clickhouse/...`) still pass after Phase 3 schema.py changes.
5. **CI dry-run:** open a draft PR editing an HCL column; confirm the CI job emits the `diff -sql`, flags `-- UNSAFE` on any destructive change, and fails on unintended golden-dump drift.

## Risks / open items

- **`query_log_archive` is fleet-wide and sensitive** — automated apply must never run destructive DDL against prod; `-- UNSAFE` is review-gated only.
- **Object ownership** must be settled in Phase 1 before deciding what the app HCL manages vs captures-as-raw.
- **`view`/`dictionary` support** in the pinned `hclexp` tag must be verified; fall back to `raw{}` if needed.
- **CI no-cloud-only-table / scoping guards** must be taught about HCL-managed tables before OPS leaves `schema.py`.
- CH-migration-PR hygiene: keep HCL-tooling/scaffolding PRs separate from any residual Python migration changes.
