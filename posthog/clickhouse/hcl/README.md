# Declarative ClickHouse schema (HCL)

Source of truth for satellite ClickHouse clusters, managed declaratively with
[`hclexp`](../../../../python-clickhouse-schema) instead of sequential Python
migrations. Schemas are written in HCL, layered for multi-environment setups,
resolved into a flat desired state, and diffed against live clusters (or
captured dumps) to produce migration DDL.

Currently covers the **OPS** cluster. LOGS is next (see
`docs/plans/2026-06-16-ops-cluster-hcl-schema.md`).

## Layout

```text
hcl/
  bin/hclexp                # wrapper: local binary or pinned container image
  ops/
    base/ops.hcl            # query_log_archive data path + ops tables/views (all envs)
    base/custom_metrics.hcl # custom_metrics Prometheus-style views (all envs)
    prod/ops.hcl            # metrics suite — prod-us + prod-eu only
    env/
      local/ops.hcl         # local dev — composes base as-is (no local-only objects yet)
      dev/ops.hcl           # prom_metrics experiment (cloud dev only)
      prod-us/ops.hcl       # events distributed proxies, sharded_tophog (tophog_new)
      prod-eu/ops.hcl       # legacy query_log_archive_old, sharded_tophog (tophog)
    golden/                 # vendored per-env cluster dumps — the drift baseline
    check.sh                # validate + diff layers vs golden for every env
```

`base/` is a single layer directory; `hclexp` loads every `*.hcl` in it, so
`base/ops.hcl` and `base/custom_metrics.hcl` are always composed together.

Each environment is the ordered composition of layers:

| Environment | Layer stack                     | Golden                          |
| ----------- | ------------------------------- | ------------------------------- |
| local       | `base` + `env/local`            | — (created from HCL; see below) |
| dev         | `base` + `env/dev`              | `golden/dev-ops.hcl`            |
| prod-us     | `base` + `prod` + `env/prod-us` | `golden/prod-us-ops.hcl`        |
| prod-eu     | `base` + `prod` + `env/prod-eu` | `golden/prod-eu-ops.hcl`        |

`local` composes the same shared `base` as cloud (so `custom_metrics` and the
`query_log_archive` data path exist locally too); it just has none of the cloud
env extras. It has no external cluster dump, so `check.sh` validates it but does
not diff it against a golden — the live round-trip is exercised by the
local-apply tooling instead.

Per-node `{shard}` / `{replica}` stay as ClickHouse macros, so the 1a/1b (1c/1d)
replicas of a cluster collapse to a single definition.

## The OPS cluster, in brief

Only `sharded_query_log_archive` (ReplicatedMergeTree, single shard) physically
lives on OPS. Every node role across the fleet also gets three companion objects
that reference it — modeled in `base/ops.hcl`:

- `query_log_archive` — Distributed **read** → `ops.sharded_query_log_archive`
- `writable_query_log_archive` — Distributed **write** → `ops.sharded_query_log_archive`
- `ops_query_log_archive_mv` — MV reading each node's `system.query_log` and
  writing through `writable_query_log_archive`.

Some objects reference tables **outside** the OPS schema by design and are
excluded from `validate` (see `SKIP` in `check.sh`): the `custom_metrics*` views
read the `system` database, the MV reads `system.query_log`, and
`events_main` / `events_recent` are Distributed proxies to the main events
cluster.

## Local apply notes

The `custom_metrics*` views read system tables (`system.part_log`,
`system.parts`, `system.backup_log`, `system.crash_log`, …). On a fresh local
ClickHouse some of these are created lazily (e.g. `system.part_log` appears only
after merge activity), so applying the views may fail with `UNKNOWN_TABLE` until
those system tables exist. This is an environment dependency, not a schema
issue; on the real clusters the system tables are always present.

(The earlier `CREATE VIEW` regeneration bug for views with a column list +
`SELECT *` — [PostHog/chschema#41](https://github.com/PostHog/chschema/issues/41)
— is fixed in `hclexp`; rebuild or pull the latest before running the tooling.)

## Common commands

Run from the repo root. Point `HCLEXP_BIN` at a built binary for fast local
iteration; CI uses the container image via the same wrapper.

```bash
HCLEXP=posthog/clickhouse/hcl/bin/hclexp

# Fidelity + reference guard for every OPS environment (CI entry point)
bash posthog/clickhouse/hcl/ops/check.sh

# Resolve a layer stack to canonical HCL
$HCLEXP load -layer posthog/clickhouse/hcl/ops/base,posthog/clickhouse/hcl/ops/env/dev -out /tmp/ops-dev.hcl

# Migration DDL to bring a live cluster up to the HCL source of truth
$HCLEXP diff \
  -left posthog/clickhouse/hcl/ops/base,posthog/clickhouse/hcl/ops/prod,posthog/clickhouse/hcl/ops/env/prod-us \
  -right 'clickhouse://user:pass@host:9440/posthog?secure=true' \
  -sql
```

`diff -sql` may flag in-place-impossible changes `-- UNSAFE`. Those are review-gated
and must never be auto-applied to production — `query_log_archive` is a
fleet-wide, sensitive table.

## Updating the schema

1. Edit the relevant layer file(s).
2. When prod changes upstream, re-dump the cluster (see the
   `../../../../python-clickhouse-schema` `dump-cluster` command) and refresh the
   matching `ops/golden/*-ops.hcl` baseline in the same change.
3. Run `check.sh` — it must report `no differences` for every environment.
4. Generate the migration DDL with `diff -sql` and apply it through the normal
   operational path.

The `golden/*-ops.hcl` files are captured cluster dumps, kept in lockstep with
the layered source so `check.sh` is a deterministic, offline CI guard.
