# Declarative ClickHouse schema (HCL)

Source of truth for satellite ClickHouse clusters, managed declaratively with
[`hclexp`](../../../../python-clickhouse-schema) instead of hand-written migrations.
Schemas are written in HCL, **composed per node** `(env, role)`, verified against
captured cluster dumps, and used to generate the migration that applies a change.

Currently covers the **OPS** and **LOGS** roles across the three cloud envs
(dev, prod-us, prod-eu); OPS also has `local`.

## Model: per-node composition

A node's schema = `compose(its layers)`. The two axes are **env** (dev/prod-us/prod-eu)
and **node role** (ops/logs/…). Placement is expressed by _which layers a node composes_,
declared once in the manifest — there is no object→roles side-table.

```text
hcl/
  bin/hclexp               # wrapper: $HCLEXP_BIN local binary, or pinned container image
  nodes                    # composition manifest: (env, role) -> ordered layer list  ← placement
  roles/shared/            # objects on every role (query_log_archive path + custom_metrics_* sub-views + ops_query_log_archive_mv)
  roles/ops/shared/        # OPS objects on every OPS env
  roles/ops/prod/          # OPS objects on both prod envs only (the metrics suite)
  roles/ops/<env>/         # per-env OPS overlay (sharded_tophog zoo_path, prod-us ProfileEvents2, dev prom_metrics); env ∈ local/dev/prod-us/prod-eu
  roles/logs/shared/       # LOGS objects on every LOGS env
  roles/logs/<env>/        # per-env LOGS overlay (kafka/zoo_path/distributed variants; traces on prod only); env ∈ dev/prod-us/prod-eu
  <layer>/sql/<object>.sql # view/MV query bodies extracted from a layer, referenced as query = file("sql/<object>.sql")
  golden/<env>-<role>.hcl  # resolved composition per node (the desired schema); check.sh diffs against it
  sql/<env>-<role>.sql     # generated build-from-scratch CREATE schema per node (apply to a fresh ClickHouse)
  check.sh                 # CI guard (offline): validate + diff every node vs golden + verify golden/ & sql/ are fresh
  dump-live.sh             # CI gate step 1 (live): introspect the migrated OPS/LOGS nodes into HCL dumps
  check-live.sh            # CI gate step 2 (offline): diff those dumps vs golden — catches migrations that desync from the HCL
  exclude.hcl              # objects the gate drops (transient + cross-cluster proxies + out-of-band-managed, not in the managed set)
  diff.sh                  # preview the DDL your uncommitted edits produce, per node
  gen-golden.sh            # (re)generate golden/  — hclexp load per node
  gen-sql.sh               # (re)generate sql/
  codegen/gen_migration.py # turn an edit into run_sql_with_exceptions(...) operations
```

## Convergence gate: migrations must reproduce the golden (`dump-live.sh` + `check-live.sh`)

`check.sh` is **offline** — it proves the HCL is internally consistent and that `golden/`/`sql/` are
fresh, but it never contacts a cluster, so it cannot tell whether the imperative migrations in
`posthog/clickhouse/migrations/` still produce the schema the HCL declares. That gap is how old
migrations silently desynced the live OPS/LOGS schema from the HCL.

The convergence gate closes it, in **two steps** that run inside the multinode migration smoke
(`tools/infra-scripts/clickhouse-multinode/`, workflow `ci-clickhouse-multinode-migrations.yml`)
**after** `manage.py migrate_clickhouse`:

1. **`dump-live.sh [outdir]`** — `hclexp introspect` each managed role's live node into
   `<outdir>/<env>-<role>.hcl`, dropping unmanaged / transient objects via `exclude.hcl`. Needs the
   cluster (a `--network host` container, or `HCLEXP_BIN` locally).
2. **`check-live.sh <dumpdir>`** — for each role, `hclexp diff -format json` the committed
   `golden/<env>-<role>.hcl` against the dump, drop the ignored operations (named_collections +
   `exclude.hcl` globs), and require nothing left. Offline — only needs `hclexp`.

```bash
DUMP=$(bash posthog/clickhouse/hcl/dump-live.sh)   # step 1 -> prints the dump dir
bash posthog/clickhouse/hcl/check-live.sh "$DUMP"  # step 2
```

Remaining drift means a migration changed the live schema without the HCL being updated (or vice
versa). Fix the migration to match the HCL, or — if the change is intended — edit the layer, rerun
`gen-golden.sh`/`gen-sql.sh`, and add the migration (the normal change flow below). Step 2 is
**enforced** (drift fails the smoke); export `VERIFY_LIVE_WARN=1` to make it informational while
reconciling a new role.

LOGS is compared against `golden/local-<role>.hcl`; until a `local-logs` golden is seeded (introspect
the live local logs node, then curate), the script skips LOGS with a notice. OPS is enforced via the
existing `golden/local-ops.hcl`.

`node_roles` is **derived**: an object in `roles/shared/` appears in every node's composition →
`node_roles` = every managed role (currently `[LOGS, OPS]`); an object under `roles/ops/` appears
only in the ops nodes → `[OPS]`; one under `roles/logs/` → `[LOGS]`.

Per-node `{shard}` / `{replica}` stay as ClickHouse macros, so replicas collapse to one definition.
Some objects reference tables outside the composed set by design (custom_metrics → `system`, the
qla MV → `system.query_log`, distributed proxies → other clusters) and are listed in `SKIP` in
`check.sh` so `validate` doesn't flag them.

## Making a change (edit HCL → migration)

Run from the repo root. All the scripts below call `hclexp` through `bin/hclexp`,
which runs the pinned container image — **no install needed, just have Docker running**:

```bash
HCL=posthog/clickhouse/hcl
# the wrapper used by every script (for running hclexp directly), e.g.:
$HCL/bin/hclexp -help
# it is equivalent to:
docker run --rm -v "$PWD:/work" -v "${TMPDIR:-/tmp}:${TMPDIR:-/tmp}" -w /work \
  ghcr.io/posthog/chschema:sha-c0affa0 -help
```

(For faster local iteration you can build the binary — `go build -o hclexp ./cmd/hclexp` in
`../../../../python-clickhouse-schema` — and `export HCLEXP_BIN=…/hclexp`; the wrapper prefers it.)

1. **Edit the right layer** for what you're changing:
   - all-role object (the `query_log_archive` path, `custom_metrics_*` sub-views, cross-cluster MVs) → `roles/shared/`
   - OPS-only → `roles/ops/shared/` (all OPS envs), `roles/ops/prod/` (both prod envs), or `roles/ops/<env>/` (one env)
   - LOGS → `roles/logs/shared/` (common) or `roles/logs/<env>/` (per-env / differing)
   - a brand-new object → add it to the layer above **and**, if it's on a new role, add that role's
     line to `nodes` (+ a golden for it).
   - a long view/MV `query` → keep it in `<layer>/sql/<object>.sql` and reference it as
     `query = file("sql/<object>.sql")` (resolved relative to the layer file). The loader normalizes
     `file()`, heredoc, and inline forms to one canonical query, so the form is purely cosmetic — edit
     the `.sql`. `gen-sql.sh`/`gen-golden.sh` emit the beautified form.

2. **Preview the DDL** the change produces, per node:

   ```bash
   bash $HCL/diff.sh            # committed HEAD -> working tree, per (env, role); flags UNSAFE
   ```

3. **Generate the migration** — `--auto` writes the next numbered migration and bumps `max_migration.txt`:

   ```bash
   python $HCL/codegen/gen_migration.py --name <slug> --auto
   ```

   It derives `node_roles` from composition and `sharded`/`is_alter_on_replicated_table` from the engine.
   Review the generated `posthog/clickhouse/migrations/NNNN_<slug>.py`: add `settings.CLOUD_DEPLOYMENT`
   gating where a statement is flagged env-specific, and recheck any `UNSAFE` (recreate) statements by hand.
   (Drop `--auto` to print to stdout instead.)

4. **Refresh the generated artifacts** so the guard passes:

   ```bash
   bash $HCL/gen-golden.sh      # rebuild golden/ (resolved compositions); optional [env] [role] filter
   bash $HCL/gen-sql.sh         # rebuild sql/
   ```

   (Golden = the desired post-apply schema; the dump pipeline re-introspects after deploy to confirm
   the real cluster converged to it.)

5. **Verify**:

   ```bash
   bash $HCL/check.sh          # validate + diff every node vs golden + sql freshness; must exit 0
   ```

The committed migration is the apply + history record; the HCL/golden/sql are the source of truth and
the offline guard. `diff -sql` UNSAFE statements (engine/zoo_path/order_by recreations) are review-gated
and must never be auto-applied to production.

## Build a node from scratch

`sql/<env>-<role>.sql` is the full, dependency-ordered CREATE schema for that node — e.g. apply
`sql/local-ops.sql` to a local ClickHouse to create the OPS schema. (It is faithful to the HCL, so it
references the real clusters / `{shard}` macros / Kafka; apply it to an env that has those configured.)
