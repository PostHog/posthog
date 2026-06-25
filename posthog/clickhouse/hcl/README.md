# Declarative ClickHouse schema (HCL)

Source of truth for satellite ClickHouse clusters, managed declaratively with
[`hclexp`](../../../../python-clickhouse-schema) instead of hand-written migrations.
Schemas are written in HCL, **composed per node** `(env, role)`, verified against
captured cluster dumps, and used to generate the migration that applies a change.

Currently covers the **OPS** and **LOGS** roles across the three cloud envs
(dev, prod-us, prod-eu); OPS also has `local`.

## Model: per-node composition

A node's schema = `compose(its layers)`. The two axes are **env** (dev/prod-us/prod-eu)
and **node role** (ops/logs/…). Placement is expressed by *which layers a node composes*,
declared once in the manifest — there is no object→roles side-table.

```text
hcl/
  bin/hclexp                 # wrapper: $HCLEXP_BIN local binary, or pinned container image
  ops/
    nodes                    # composition manifest: (env, role) -> ordered layer list  ← placement
    shared/                  # objects identical on every role (query_log_archive path + custom_metrics_* sub-views)
    roles/ops/, roles/ops-prod/   # OPS-only objects (ops-prod = prod envs only)
    roles/logs/              # LOGS objects identical across all cloud envs
    env/<env>/ops.hcl        # per-env OPS overlays (sharded_tophog zoo_path, prod-us ProfileEvents2, dev prom_metrics)
    env-logs/<env>/          # per-env LOGS overlays (kafka/zoo_path/distributed variants; traces on prod only)
    golden/<env>-<role>.hcl  # resolved composition per node (the desired schema); check.sh diffs against it
    sql/<env>-<role>.sql     # generated build-from-scratch CREATE schema per node (apply to a fresh ClickHouse)
    check.sh                 # CI guard: validate + diff every node vs golden + verify golden/ & sql/ are fresh
    diff.sh                  # preview the DDL your uncommitted edits produce, per node
    gen-golden.sh            # (re)generate golden/  — hclexp load per node
    gen-sql.sh               # (re)generate sql/
    codegen/gen_migration.py # turn an edit into run_sql_with_exceptions(...) operations
```

`node_roles` is **derived**: an object in `shared/` appears in every node's composition →
`node_roles` = every managed role (currently `[LOGS, OPS]`); an object in `roles/ops/` appears
only in the ops nodes → `[OPS]`; a `roles/logs/` object → `[LOGS]`.

Per-node `{shard}` / `{replica}` stay as ClickHouse macros, so replicas collapse to one definition.
Some objects reference tables outside the composed set by design (custom_metrics → `system`, the
qla MV → `system.query_log`, distributed proxies → other clusters) and are listed in `SKIP` in
`check.sh` so `validate` doesn't flag them.

## Making a change (edit HCL → migration)

Run from the repo root. All the scripts below call `hclexp` through `ops/bin/hclexp`,
which runs the pinned container image — **no install needed, just have Docker running**:

```bash
OPS=posthog/clickhouse/hcl/ops
# the wrapper used by every script (for running hclexp directly), e.g.:
$OPS/bin/hclexp -help
# it is equivalent to:
docker run --rm -v "$PWD:/work" -v "${TMPDIR:-/tmp}:${TMPDIR:-/tmp}" -w /work \
  ghcr.io/posthog/chschema:sha-f9490b7 -help
```

(For faster local iteration you can build the binary — `go build -o hclexp ./cmd/hclexp` in
`../../../../python-clickhouse-schema` — and `export HCLEXP_BIN=…/hclexp`; the wrapper prefers it.)

1. **Edit the right layer** for what you're changing:
   - all-role object (the `query_log_archive` path, `custom_metrics_*` sub-views) → `shared/`
   - OPS-only → `roles/ops/` (all envs), `roles/ops-prod/` (prod only), or `env/<env>/ops.hcl` (one env)
   - LOGS → `roles/logs/` (common) or `env-logs/<env>/` (per-env / differing)
   - a brand-new object → add it to the layer above **and**, if it's on a new role, add that role's
     line to `nodes` (+ a golden for it).

2. **Preview the DDL** the change produces, per node:
   ```bash
   bash $OPS/diff.sh            # committed HEAD -> working tree, per (env, role); flags UNSAFE
   ```

3. **Generate the migration** — `--auto` writes the next numbered migration and bumps `max_migration.txt`:
   ```bash
   python $OPS/codegen/gen_migration.py --name <slug> --auto
   ```
   It derives `node_roles` from composition and `sharded`/`is_alter_on_replicated_table` from the engine.
   Review the generated `posthog/clickhouse/migrations/NNNN_<slug>.py`: add `settings.CLOUD_DEPLOYMENT`
   gating where a statement is flagged env-specific, and recheck any `UNSAFE` (recreate) statements by hand.
   (Drop `--auto` to print to stdout instead.)

4. **Refresh the generated artifacts** so the guard passes:
   ```bash
   bash $OPS/gen-golden.sh      # rebuild golden/ (resolved compositions); optional [env] [role] filter
   bash $OPS/gen-sql.sh         # rebuild sql/
   ```
   (Golden = the desired post-apply schema; the dump pipeline re-introspects after deploy to confirm
   the real cluster converged to it.)

5. **Verify**:
   ```bash
   bash $OPS/check.sh          # validate + diff every node vs golden + sql freshness; must exit 0
   ```

The committed migration is the apply + history record; the HCL/golden/sql are the source of truth and
the offline guard. `diff -sql` UNSAFE statements (engine/zoo_path/order_by recreations) are review-gated
and must never be auto-applied to production.

## Build a node from scratch

`sql/<env>-<role>.sql` is the full, dependency-ordered CREATE schema for that node — e.g. apply
`sql/local-ops.sql` to a local ClickHouse to create the OPS schema. (It is faithful to the HCL, so it
references the real clusters / `{shard}` macros / Kafka; apply it to an env that has those configured.)
