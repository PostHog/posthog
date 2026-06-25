# OPS HCL → migration codegen

Turns a declarative-HCL change into a ClickHouse migration the existing
`infi.clickhouse_orm` runner executes. The HCL is the source of truth for *what*
the schema is; this produces the `run_sql_with_exceptions(...)` operations for
*applying* it — with the cluster targeting derived from **composition**, not a
side-table.

## How it works

```
edit OPS HCL ─▶ for each (env, role) node in ../nodes: hclexp diff -sql (committed → working)
            ─▶ gen_migration.py: collect statements, derive targeting
            ─▶ operations = [run_sql_with_exceptions(...), ...]
```

A node's schema = `compose(its layers)` (see `../nodes`). Placement falls out of it:

- **`node_roles`** = the roles whose composition surfaced a statement. A change to a
  `shared/` object appears in every managed role's node → `node_roles` = those roles
  (the pilot manages OPS + LOGS, so `[LOGS, OPS]`); a change to an OPS-only object
  (`roles/ops*`, `env/*`) appears only in the ops nodes → `node_roles = [OPS]`.
- **`is_alter_on_replicated_table`** = ALTER on a `Replicated*` MergeTree (engine).
- **`sharded`** = replicated *and* on the multi-shard DATA cluster.
- **Env-specific** statements (only some envs) are flagged for `settings.CLOUD_DEPLOYMENT`
  gating.

There is no object→roles map — `../nodes` (the composition manifest) is the single
source of truth for placement.

## Usage

Runs `hclexp` via `ops/bin/hclexp` (the pinned ghcr.io image) — just have Docker running:

```bash
python posthog/clickhouse/hcl/ops/codegen/gen_migration.py --name add_foo_column
#   --ref <git-ref>   diff the working tree against this ref (default HEAD)
#   --out <path|->    write here, or stdout (default)
# (optional: export HCLEXP_BIN=…/hclexp to use a local binary instead of Docker)
```

Then: review the output, save it as the next `posthog/clickhouse/migrations/NNNN_<name>.py`,
and bump `max_migration.txt`.

## Guardrails / limitations

- **UNSAFE changes are flagged** (`# UNSAFE (review/recreate by hand)`); never emitted
  silently as a plain ALTER.
- Env-specific statements get a `# NOTE: only [...] — gate with settings.CLOUD_DEPLOYMENT`
  comment; the human writes the `CLOUD_DEPLOYMENT` branch (auto-gating is a follow-up).
- Output goes to stdout; placement as the next numbered migration + `max_migration.txt`
  bump is manual.
- Scoped to OPS + LOGS (see `../nodes`). Other roles that also host the shared
  `query_log_archive` path are commented out, so shared-object changes target only
  OPS + LOGS; `events_recent` derives as OPS-only until the DATA node is modeled.

## Adding/moving objects

Placement is the manifest + which layer a file lives in. Put shared (all-role) objects
in `shared/`, OPS-only in `roles/ops*` or `env/*`, and add the (env, role) line to
`../nodes`. `check.sh` verifies every composition against its golden.
