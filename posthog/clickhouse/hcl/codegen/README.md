# OPS HCL → migration codegen

Turns a declarative-HCL change into a ClickHouse migration the existing
`infi.clickhouse_orm` runner executes. The HCL is the source of truth for _what_
the schema is; this produces the `run_sql_with_exceptions(...)` operations for
_applying_ it — with the cluster targeting derived from **composition**, not a
side-table.

## How it works

```text
edit OPS HCL ─▶ for each env in ../nodes: hclexp plan (committed goldens ─▶ working composition)
            ─▶ gen_migration.py: merge across envs, derive targeting
            ─▶ operations = [run_sql_with_exceptions(...), ...]
```

`plan` diffs the **committed goldens** (current managed state) against the working-tree
composition for every role of an env at once. Goldens hold only the managed set, so a
`DROP` is a real removal — nothing unmanaged to prune — and `plan` unions roles and
orders statements by cross-role dependency, so each operation arrives with its `roles`,
engine, and order already resolved (no text parsing). A node's schema =
`compose(its layers)` (see `../nodes`); placement falls out of it:

- **`node_roles`** = the roles whose composition surfaced a statement. A change to a
  `roles/shared/` object appears in every managed role's node → `node_roles` = those roles
  (the pilot manages OPS + LOGS, so `[LOGS, OPS]`); a change to an OPS-only object
  (under `roles/ops/`) appears only in the ops nodes → `node_roles = [OPS]`.
- **`is_alter_on_replicated_table`** = ALTER on a `Replicated*` MergeTree (engine).
- **`sharded`** = replicated _and_ on the multi-shard DATA cluster.
- **Env-specific** statements (only some envs) are flagged for `settings.CLOUD_DEPLOYMENT`
  gating.

There is no object→roles map — `../nodes` (the composition manifest) is the single
source of truth for placement.

## Usage

Runs `hclexp` via `bin/hclexp` (the pinned ghcr.io image) — just have Docker running:

```bash
python posthog/clickhouse/hcl/codegen/gen_migration.py --name add_foo_column --auto
#   --auto            write the next posthog/clickhouse/migrations/NNNN_<name>.py and bump max_migration.txt
#   --ref <git-ref>   the golden baseline to diff the working tree against (default HEAD)
#   --out <path|->    without --auto: write here, or stdout (default)
# (optional: export HCLEXP_BIN=…/hclexp to use a local binary instead of Docker)
```

Then: review the output, save it as the next `posthog/clickhouse/migrations/NNNN_<name>.py`,
and bump `max_migration.txt`.

## Guardrails / limitations

- **UNSAFE changes are flagged** (`# UNSAFE (review/recreate by hand)`); never emitted
  silently as a plain ALTER.
- Env-specific statements get a `# NOTE: only [...] — gate with settings.CLOUD_DEPLOYMENT`
  comment; the human writes the `CLOUD_DEPLOYMENT` branch (auto-gating is a follow-up).
- `--auto` writes the next numbered `migrations/NNNN_<name>.py` and bumps `max_migration.txt`;
  without it the body goes to stdout (or `--out`) for manual placement.
- Scoped to OPS + LOGS (see `../nodes`). Other roles that also host the shared
  `query_log_archive` path are commented out, so shared-object changes target only
  OPS + LOGS; `events_recent` derives as OPS-only until the DATA node is modeled.

## Adding/moving objects

Placement is the manifest + which layer a file lives in. Put cross-role objects in
`roles/shared/`, OPS-only in `roles/ops/<shared|prod|env>/`, and add the (env, role) line
to `../nodes`. `check.sh` verifies every composition against its golden.
