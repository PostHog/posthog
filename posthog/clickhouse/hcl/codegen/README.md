# OPS HCL → migration codegen

Turns a declarative-HCL change into a ClickHouse migration the existing
`infi.clickhouse_orm` runner executes. The HCL is the source of truth for _what_
the schema is; this produces the `run_sql_with_exceptions(...)` operations for
_applying_ it — with the cluster targeting derived from **composition**, not a
side-table.

## How it works

```text
edit OPS HCL ─▶ for each env in ../manifest.hcl: hclexp plan (committed goldens ─▶ working composition)
            ─▶ gen_migration.py: merge across envs, derive targeting
            ─▶ operations = [run_sql_with_exceptions(...), ...]
```

`plan` diffs the **committed goldens** (current managed state) against the working-tree
composition for every role of an env at once. Goldens hold only the managed set, so a
`DROP` is a real removal — nothing unmanaged to prune — and `plan` unions roles and
orders statements by cross-role dependency, so each operation arrives with its `roles`,
engine, and order already resolved (no text parsing). A node's schema =
`compose(its layers)` (see `../manifest.hcl`); placement falls out of it:

- **`node_roles`** = the roles whose composition surfaced a statement. A change to a
  `roles/shared/` object appears in every managed role's node → `node_roles` = those roles
  (the pilot manages OPS + LOGS, so `[LOGS, OPS]`); a change to an OPS-only object
  (under `roles/ops/`) appears only in the ops nodes → `node_roles = [OPS]`.
- **`is_alter_on_replicated_table`** = ALTER on a `Replicated*` MergeTree (engine).
- **`sharded`** = replicated _and_ on the multi-shard DATA cluster.
- **Env-specific** statements (only some envs) are flagged for `settings.CLOUD_DEPLOYMENT`
  gating.

There is no object→roles map — `../manifest.hcl` (the composition manifest) is the single
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
- Scoped to OPS + LOGS (see `../manifest.hcl`). Other roles that also host the shared
  `query_log_archive` path are commented out, so shared-object changes target only
  OPS + LOGS; `events_recent` derives as OPS-only until the DATA node is modeled.

## Adding/moving objects

Placement is the manifest + which layer a file lives in. Put cross-role objects in
`roles/shared/`, OPS-only in `roles/ops/<shared|prod|env>/`, and add the (env, role) line
to `../manifest.hcl`. `check.sh` verifies every composition against its golden.

## Extracting a golden or a self-contained layer from a live node

Most nodes compose from shared layers, but some cannot: a node whose live schema is a
partial/newer variant (`roles/logs/local`) or one whose objects collide across layers and
resolve inconsistently (`roles/single/local` — `person` is DATA's storage table while
`ai_events`/`message_assets`/`query_log_archive` are satellite proxies, and no layer order
reproduces that mix). For those, and to bring a new role under management (`../manifest.hcl`
notes this next to each such role), extract the desired state straight from a migrated node:

1. **Boot the node and migrate it.** For the single-node dev stack, free `:9000` from the
   multinode containers first, then bring up `docker-compose.dev.yml`'s clickhouse and run
   `DEBUG=1 python manage.py migrate_clickhouse`. For a cloud role, point at a host of that
   role. (Prod DATA goldens live in `posthog-cloud-infra`, not here.)
2. **Introspect into HCL**, dropping transient/unmanaged objects with the matching exclude
   file (`exclude-<env>.hcl` when the env has one, else `exclude.hcl`):

   ```bash
   hclexp introspect -host localhost -port 9000 -database posthog -node all \
     -exclude posthog/clickhouse/hcl/exclude-local-single.hcl \
     -out posthog/clickhouse/hcl/roles/single/local/tables.hcl
   ```

3. **Strip the leading `node { … }` block.** `introspect` emits one; layer files carry none
   (`roles/**` has zero `^node "`). Query bodies stay inline — the self-contained layers do
   not use a `sql/` subdir.
4. **Regenerate and verify:** `bash gen-golden.sh <env> && bash gen-sql.sh`, then
   `bash check.sh` (offline: composition vs golden) and, for a self-sufficient node,
   `hclexp validate -manifest manifest.hcl -env <env> -layer-root . -strict-clusters`.
