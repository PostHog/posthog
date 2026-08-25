# Declarative ClickHouse schema (HCL)

Source of truth for satellite ClickHouse clusters, managed declaratively with
[`hclexp`](../../../../python-clickhouse-schema) instead of hand-written migrations.
Schemas are written in HCL, **composed per node** `(env, role)`, verified against
captured cluster dumps, and used to generate the migration that applies a change.

Covers the satellite roles (logs, aux, `ai_events`, sessions, sessionsv3, `batch_exports`) in the cloud envs (dev, prod-us, prod-eu) where each exists, plus the local `data` node and the three ingestion roles (`events`, `small`, `medium`) the multinode stack runs.
`ops` is local-only here: posthog-cloud-infra authors its cloud env layers and goldens, composing `roles/ops/shared` vendored from this directory.
The `local-single` env models the plain dev stack, where one server hosts every role's objects under the role `all`, composed as the union of the roles the multinode stack splits across nodes.
The prod data clusters carry per-env `mat_` columns, so their goldens and per-env override layers live in posthog-cloud-infra (see [The cloud side](#the-cloud-side-posthog-cloud-infra)).

## Model: per-node composition

A node's schema = `compose(its layers)`. The two axes are **env** (dev/prod-us/prod-eu)
and **node role** (ops/logs/…). Placement is expressed by _which layers a node composes_,
declared once in the manifest — there is no object→roles side-table.

```text
hcl/
  bin/hclexp               # wrapper: $HCLEXP_BIN, `hclexp` on $PATH, or the pinned container image
  bin/image.txt            # the pinned chschema image tag — the one place to bump
  bin/install-hclexp       # extract the pinned binary onto $PATH (what CI does)
  manifest.hcl             # composition manifest, consumed by hclexp itself  ← placement
                           #   role "<role>" { env "<env>" { layers = [...] } }  -> a node's layer stack
                           #   cluster "<name>" { roles = [...], aliases = [...] } -> cross-cluster proxy resolution
  lib.sh                   # shared manifest helpers sourced by the scripts below
  roles/shared/            # objects on every role (the query_log_archive path + custom_metrics_* sub-views)
  roles/coshared/<set>/    # objects co-hosted by a specific SET of roles (aux_data, sessions_data, tophog, …) — one layer per member set
  roles/<role>/shared/     # objects on every env of one role
  roles/<role>/prod/       # objects on both prod envs only
  roles/<role>/<env>/      # per-env overlay: env-only objects + patch_* deltas; env ∈ local/dev/prod-us/prod-eu
  roles/data/shared/       # the events family declared once: the _event_base abstract + the events/sharded_events extenders
  roles/data/local/        # the rest of the local data node (migration-produced schema) + its patch_* deltas
  duplicates-baseline.txt  # objects still declared in >1 composed layer; check.sh gates on it, and it only shrinks
  <layer>/sql/<object>.sql # view/MV query bodies extracted from a layer, referenced as query = file("sql/<object>.sql")
  golden/<env>/<role>.hcl  # resolved composition per node (the desired schema); check.sh diffs against it
  sql/<env>/<role>.sql     # generated build-from-scratch CREATE schema per node (apply to a fresh ClickHouse)
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
migrations silently desynced the live schema from the HCL.

The convergence gate closes it, in **two steps** that run inside the multinode migration smoke
(`tools/infra-scripts/clickhouse-multinode/`, workflow `ci-clickhouse-multinode-migrations.yml`)
**after** `manage.py migrate_clickhouse`:

1. **`dump-live.sh [outdir]`** — `hclexp introspect` each role's live node into
   `<outdir>/<env>-<role>.hcl`, dropping unmanaged / transient objects via `exclude.hcl`. Needs the
   cluster (a `--network host` container, or `HCLEXP_BIN` locally). Also writes
   `<outdir>/hclexp-version.txt` (`hclexp -version`) recording the tool build that produced the dump —
   informational provenance, not gated by `check-live.sh`.
2. **`check-live.sh <dumpdir>`** — for each role, `hclexp diff -exclude exclude.hcl -format json` the
   committed `golden/<env>/<role>.hcl` against the dump, and require an empty operation list.
   The exclusion is native: `hclexp` drops named_collections (`object_types`) and unmanaged /
   transient names (`patterns`) from both sides before diffing, so `check-live.sh` filters nothing
   itself. Offline — only needs `hclexp`.

```bash
DUMP=$(bash posthog/clickhouse/hcl/dump-live.sh)   # step 1 -> prints the dump dir
bash posthog/clickhouse/hcl/check-live.sh "$DUMP"  # step 2
```

Remaining drift means a migration changed the live schema without the HCL being updated (or vice
versa). Fix the migration to match the HCL, or — if the change is intended — edit the layer, rerun
`gen-golden.sh`/`gen-sql.sh`, and add the migration (the normal change flow below). Step 2 is
**enforced** (drift fails the smoke); export `VERIFY_LIVE_WARN=1` to make it informational while
reconciling a new role.

Every role `manifest.hcl` composes for the gate's env is dumped and gated — for `local-multi` that is
each node the multinode stack runs, one per published port in `dump-live.sh`'s `ROLES`, compared
against its `golden/local-multi/<role>.hcl` (`aux` is filed as `auxiliary`, see `golden_name` in
`lib.sh`). Every logs node composes `roles/logs/{base,traces,traces_kafka_metrics}`; the local one
adds a self-contained `roles/logs/local` (extracted from the live node) for the legacy `logs32`
family it still runs, and skips the cloud-only metrics ingest in `roles/logs/cloud`.

`node_roles` is **derived**: an object in `roles/shared/` appears in every node's composition →
`node_roles` = every role the manifest declares; an object under `roles/ops/` appears only in the ops
nodes → `[OPS]`; one under `roles/logs/` → `[LOGS]`.

Per-node `{shard}` / `{replica}` stay as ClickHouse macros, so replicas collapse to one definition.
A cross-cluster Distributed proxy references a table on another cluster's composition; `check.sh`
runs `validate -manifest manifest.hcl -env <env>`, so those
remotes resolve against their target cluster (existence + column agreement) rather than being
skipped. `system.*` remotes are always resolvable. The `posthog` data cluster is `local`-only here
(prod goldens live in posthog-cloud-infra), so `check.sh` passes it via `-cluster` flags — composed
for `local`, `@absent` elsewhere. A tiny `known_drift_skip` covers real proxy/storage drift pending
a fix.

## The cloud seam: vendored layers and the compose gate

posthog-cloud-infra composes its cloud envs (dev, prod-us, prod-eu) from base layers vendored out of this directory at a pinned `base-ref` — today `roles/shared/` and `roles/data/shared/`, growing as roles migrate.
Editing a vendored layer therefore changes compositions in another repo.
Two consequences:

- The **Cloud compose gate** job (in `ci-clickhouse-hcl-schema.yml`) dispatches to posthog-cloud-infra and composes the cloud envs against your PR head; it fails when a change breaks composition there (a patch that no longer resolves, a redeclaration, a validation error).
- A change that composes cleanly may still legitimately _shift_ cloud goldens (say, a new column on `_event_base`) — that regen happens in cloud-infra's next `base-ref` bump PR, not here, and is expected.

The events family is the canonical example: `roles/data/shared/` declares `_event_base` + `sharded_events` + `events` once; cloud env deltas (mat\_ columns, env specs) live as patches in cloud-infra's `overrides/`.
Schema changes to those tables belong in `roles/data/shared/`, never re-declared per env.

## Making a change (edit HCL → migration)

Run from the repo root. All the scripts below call `hclexp` through `bin/hclexp`,
which runs the pinned container image — **no install needed, just have Docker running**:

```bash
HCL=posthog/clickhouse/hcl
# the wrapper used by every script (for running hclexp directly), e.g.:
$HCL/bin/hclexp -help
# it is equivalent to:
docker run --rm -v "$PWD:/work" -v "${TMPDIR:-/tmp}:${TMPDIR:-/tmp}" -w /work \
  "$(cat $HCL/bin/image.txt)" -help
```

The image tag is pinned in `bin/image.txt` — the one place to bump when upgrading hclexp.
The wrapper resolves `$HCLEXP_BIN` → `hclexp` on `$PATH` → that image, so a native binary always
wins: run `bash $HCL/bin/install-hclexp` to extract one from the pinned image (what CI does), or
build it yourself with `go build -o hclexp ./cmd/hclexp` in `../../../../python-clickhouse-schema`.

1. **Edit the right layer** for what you're changing.
   Placement = which node stacks compose the layer, declared in `manifest.hcl`; find an existing object's single declaration with `hclexp locate` (or grep) rather than assuming:
   - an object on every role (the `query_log_archive` path, `custom_metrics_*` sub-views) → `roles/shared/`
   - an object a specific set of roles co-hosts (a data table plus the nodes holding its Distributed proxies) → `roles/coshared/<member-set>/`, and wire a new set into each member's stack in `manifest.hcl`
   - one role → `roles/<role>/shared/` (all its envs), `roles/<role>/prod/` (both prods), or `roles/<role>/<env>/` (one env)
   - the events family → the `_event_base` abstract + extenders in `roles/data/shared/`
   - a brand-new object → add it to the layer above **and**, if it's on a new role, add that role's
     block to `manifest.hcl` (+ a golden for it).
   - **declare an object once, everywhere it differs use a patch.**
     An env/role variant is expressed on top of the single declaration: `patch_table` / `patch_view` / `patch_dictionary` / `patch_materialized_view` in the differing stack's layer, or `extend` + `patch_column` for shared column lists.
     Never paste a second declaration — `check.sh` gates `hclexp locate -duplicates` against `duplicates-baseline.txt`, which may only shrink.
     A cloud-only difference (e.g. `mat_` columns) belongs in posthog-cloud-infra's `overrides/`, never here.
     Counting rules and the full patch vocabulary: [migration.md](migration.md).
   - a long view/MV `query` → keep it in `<layer>/sql/<object>.sql` and reference it as
     `query = file("sql/<object>.sql")` (resolved relative to the layer file). The loader normalizes
     `file()`, heredoc, and inline forms to one canonical query, so the form is purely cosmetic — edit
     the `.sql`. `gen-sql.sh`/`gen-golden.sh` emit the beautified form.
   - a column list shared by a sharded table and its Distributed siblings → an `abstract` table the
     instances `extend`, kept codec-free. Most tables need no codec at all — the server already
     compresses with ZSTD, and `posthog/clickhouse/migrations/AGENTS.md` has the rule for the rare
     column that earns one. Where a column does, add it to the storage instance alone via
     `patch_column "<col>" { codec = ... }`: a Distributed table stores nothing, so a codec there is
     inert metadata that only invites the two column lists to drift.

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

### Recipes

**Add a column to an existing table.**
Find the table's single declaration (`hclexp locate`, or grep the layers) and add the `column` block there — every env composing that layer gets it, which is the point of declaring once.
On an `extend` family, adding to the abstract (e.g. `_event_base`) reaches every extender; adding to one child reaches only that table.
If only some envs should have the column, leave the declaration alone and add it via `patch_table { column "…" { … } }` in those envs' layers instead.
Then steps 2–5 above: `diff.sh`, `gen_migration.py`, `gen-golden.sh`/`gen-sql.sh`, `check.sh`.

**Add an index (or projection).**
Same placement logic, with an `index` block inside the single table declaration (`expression`/`type`/`granularity`), or `patch_table { index "…" { … } }` for an env-only index.
`after` positions it; redefining an inherited index in a patch means drop + re-add in the same patch.
Note the generated `ADD INDEX` only affects newly written parts; backfilling it (`MATERIALIZE INDEX`) is a separate, deliberate operation to add by hand if history needs it.

**Add a new table.**
Declare it in the placement layer per step 1 (a Kafka table + MV + storage/Distributed group usually lands together in one layer), keep long view/MV queries in `<layer>/sql/<object>.sql`, and run the same steps 2–5.
If the table introduces a new role, add the `role` block to `manifest.hcl` and a golden for it.

**Change an env-specific variant.**
Edit the existing `patch_*` block in that env's layer (cloud envs: in posthog-cloud-infra's `overrides/`); the base declaration stays untouched.

## What CI runs on a PR touching this directory

- **`hcl-guard`** (`ci-clickhouse-hcl-schema.yml`, offline): `check.sh` — validate + compose every node, byte-compare against `golden/`, verify `sql/` freshness, and hold `locate -duplicates` to `duplicates-baseline.txt`.
- **`cloud-compose-gate`** (same workflow): dispatches posthog-cloud-infra to compose **your PR's ref** as the vendored base under its `overrides/`, per cloud env.
  It fails when a base change breaks the cloud composition — a renamed/dropped column a cloud patch targets, a name colliding with a cloud-added column, a reference a cloud-only object needs.
  It deliberately does **not** assert cloud goldens: a legitimate shared-layer change shifts them, and regenerating is the base-ref bump PR's job (below).
  The job skips (with a summary) on fork PRs and while the gate's App credentials are unprovisioned.
- **Convergence gate** (multinode smoke, see above): proves the imperative migrations still reproduce the local goldens on a live cluster.

## The cloud side (posthog-cloud-infra)

The cloud envs compose the same base layers, vendored by commit sha, plus private per-env `overrides/` (mat\_ columns and other cloud-only deltas), in posthog-cloud-infra's `clickhouse/hcl/`.
After a base change merges here, a **base-ref bump PR** there advances the pinned sha, regenerates the cloud goldens (your change now appears in every env's composed output), and produces the ordered migration SQL for the cloud clusters.
That PR runs the strict check (goldens asserted, baseline exact), so the golden movement the compose gate waved through gets reviewed and applied there.

## Build a node from scratch

`sql/<env>/<role>.sql` is the full, dependency-ordered CREATE schema for that node — e.g. apply
`sql/local-multi/ops.sql` to a local ClickHouse to create the OPS schema. (It is faithful to the HCL, so it
references the real clusters / `{shard}` macros / Kafka; apply it to an env that has those configured.)
