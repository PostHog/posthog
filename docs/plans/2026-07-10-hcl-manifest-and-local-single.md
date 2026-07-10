# hclexp bump + `manifest.hcl` + a `local-single` node

> First implementation step: copy this file to `docs/plans/2026-07-10-hcl-manifest-and-local-single.md`
> (repo convention) and work from there.

## Context

`posthog/clickhouse/hcl/` describes the satellite ClickHouse clusters declaratively and gates them in CI.
It pins `hclexp` (the `chschema` tool) at `ghcr.io/posthog/chschema:sha-0409212`.

Three things are now out of date:

1. **The pin is stale.** The current build is `sha-e860af4` (`hclexp v0.1.1-9-ge860af4`), verified pullable.
   It adds `load -manifest -env [-role] [-format json]` (chschema #133) and makes `load -format json`
   resolve layer stacks _from the manifest alone_, without the layer dirs existing (#134).

2. **We carry a redundant `nodes` file.** `hclexp` has always consumed an HCL `manifest.hcl`
   (role blocks + cluster blocks). Because `load` could not read it, this repo kept a flat
   whitespace-delimited `nodes` file plus a `clusters` file, and **four** consumers each re-derive the
   real manifest from them: `check.sh` (an awk renderer, `render_manifest`), `gen-golden.sh`,
   `gen-sql.sh`, `diff.sh`, and `codegen/gen_migration.py` (`write_manifest_hcl`). Parsing HCL with awk
   to feed the tool that already parses HCL is the wrong shape — it breaks on comments containing `]`,
   heredocs, and multi-line arrays. chschema #133's own commit message names this repo as the reason it
   was written. With #133/#134 the shell needs no knowledge of layers at all.

3. **The ordinary dev stack is unmodelled.** Every `local` golden today comes from
   `docker-compose.multinode-clickhouse.yml` — six ClickHouse servers on ports 9000–9500. But
   `bin/start` runs **one** ClickHouse node, and `migration_tools.py:75` routes every migration to
   `NodeRole.ALL` when `DEBUG and not MULTINODE_CLICKHOUSE`. So the schema most engineers actually run is
   the one node nothing describes, checks, or can rebuild from `sql/`.

Outcome: one committed `manifest.hcl` as the single source of truth for composition and cluster mapping,
every script driving `hclexp` directly, CI running a native binary instead of a container per call, and a
`local-single` node with a golden, a build-from-scratch SQL file, and a live-dump path.

## Work

### 1. Bump the pin to `sha-e860af4`

Mechanical, five places:

| File                                                       | Line                            |
| ---------------------------------------------------------- | ------------------------------- |
| `posthog/clickhouse/hcl/bin/hclexp`                        | 15 (`HCLEXP_IMAGE=`)            |
| `posthog/clickhouse/hcl/dump-live.sh`                      | 47 (its own `HCLEXP_IMAGE=`)    |
| `posthog/clickhouse/hcl/README.md`                         | ~100 (the `docker run` example) |
| `.github/workflows/ci-clickhouse-hcl-schema.yml`           | 32                              |
| `.github/workflows/ci-clickhouse-multinode-migrations.yml` | 60                              |

### 2. CI runs the binary, not a container per call

Both workflows do `docker pull "$HCLEXP_IMAGE"` and then every `hclexp` invocation pays container startup.
`chschema` publishes no binary release asset, but the distroless image has the static binary at `/hclexp`
(chschema `Dockerfile:43`), so extract it once per job:

```yaml
- name: Install hclexp
  run: |
    docker pull "$HCLEXP_IMAGE"
    cid=$(docker create "$HCLEXP_IMAGE")
    docker cp "$cid:/hclexp" /usr/local/bin/hclexp
    docker rm "$cid"
    hclexp -version
```

`bin/hclexp` already resolves `$HCLEXP_BIN` → `hclexp` on `$PATH` → the image, so **no wrapper change** —
CI simply stops reaching the container branch.

`dump-live.sh` has its own `run_hclexp()` that only checks `$HCLEXP_BIN`; give it the same `$PATH` lookup.
That also removes the need for `docker run --network host` in the multinode smoke, since the binary reaches
`localhost:9000..9500` directly.

### 3. `manifest.hcl` replaces `nodes` + `clusters`

**New:** `posthog/clickhouse/hcl/manifest.hcl` — the schema `hclexp` already decodes
(`cmd/hclexp/plan.go:27-56`):

```hcl
role "ops" {
  env "local"   { layers = ["roles/shared", "roles/ops/shared", "roles/ops/local"] }
  env "dev"     { layers = ["roles/shared", "roles/ops/shared", "roles/ops/dev"] }
  env "prod-us" { layers = ["roles/shared", "roles/ops/shared", "roles/ops/prod", "roles/ops/prod-us"] }
  env "prod-eu" { layers = ["roles/shared", "roles/ops/shared", "roles/ops/prod", "roles/ops/prod-eu"] }
}
# ... logs, ai_events, aux, sessions, sessionsv3, batch_exports, data, all

cluster "ops"     { roles = ["ops"] }
cluster "posthog" { roles = ["data"], aliases = ["posthog_writable", "posthog_primary_replica", "posthog_single_shard"] }
```

Carry over every explanatory comment from `nodes` and `clusters` — they are the only prose explaining why
`local logs` is self-contained, why the prod `data` goldens live in `posthog-cloud-infra`, and why
`node_roles` is derived rather than declared. Then **delete `nodes` and `clusters`**, and drop the
`.gitignore` entry for `.hcl-manifest.*`.

Consumers, all of which lose their layer-stack knowledge:

- **`check.sh`** — delete `render_manifest`, `csv_items`, `emit_hcl_list`, the mktemp/trap. Env list from
  `grep -oE 'env "[^"]+"' manifest.hcl` (label extraction, not HCL parsing — the labels are single-line).
  Per env: `validate -manifest manifest.hcl -env "$env" -layer-root "$HCL" -skip-validation …`, then
  `load -manifest manifest.hcl -env "$env" -layer-root "$HCL" -out "$tmp"` (one `<env>-<role>.hcl` per
  role) and `diff -left "$tmp/$env-$role.hcl" -right "golden/$env-$role.hcl"` per role. Keep the
  semantic `hclexp diff` rather than `diff -r`: it survives cosmetic formatting changes across hclexp
  builds. Roles per env come from `load … -format json`.
- **`gen-golden.sh`** — collapses to one call per env: `load -manifest … -env "$env" -out "$GOLDEN"`.
  The optional `[env] [role]` filters map onto `-env` / `-role`.
- **`gen-sql.sh`** — take the resolved stacks from `load -manifest -env "$env" -format json`
  (`.roles[] | {role, resolved_layers}`), keep the existing `diff -left <empty schema> -right <stack> -sql`.
- **`diff.sh`** — same JSON source for the stacks. Because #134 resolves stacks without the dirs existing,
  the committed-tree stack can be resolved from the `git archive` copy's manifest. Replace the hardcoded
  `ops|data|endpoints|aux|ai_events|sessions` role filter (already stale: no `logs`, `batch_exports`,
  `sessionsv3`) with a check against the manifest's roles.
- **`codegen/gen_migration.py`** — delete `read_manifest()` and `write_manifest_hcl()`; point
  `plan -manifest` at the committed `manifest.hcl`. Envs via `re.findall(r'env "([^"]+)"', ...)`;
  env→roles from `load -manifest -env E -format json`. `write_dump()` and everything downstream is unchanged.
- **`check-live.sh`** — derive `ROLES` for `$VERIFY_LIVE_ENV` from the manifest instead of the hardcoded
  `(data ops logs ai_events aux sessions)`.
- **`README.md` + `codegen/README.md`** — every `../nodes` / `clusters` reference becomes `manifest.hcl`;
  update the tree diagram and the "no object→roles side-table" paragraph.

**Upstream gap:** there is no way to ask `hclexp` which envs a manifest declares (`-format json` requires
`-env`), which is why the env list is grepped. Per repo convention this gets filed as a **PostHog/chschema
issue**, not implemented here.

### 4. The `local-single` node

**Naming:** env `local-single`, role `all` (matches `NodeRole.ALL`, which is literally what
`migration_tools.py` routes to in this mode) → `golden/local-single-all.hcl`, `sql/local-single-all.sql`.
The existing multinode `local` env is untouched.

**No cluster-block change is needed.** I checked `resolveDistributedRemote`
(chschema `internal/loader/hcl/validate.go:618`): a Distributed remote declared in the node's _own_ schema
resolves at step 1, before any cluster lookup. On the single node every remote is local, so `ops`/`logs`/…
resolving `@absent` for this env is harmless. That also means `validate -env local-single -strict-clusters`
should pass — worth asserting, since it proves the node is self-sufficient.

**Getting the dump** (port 9000 is currently held by the multinode `data` container):

```bash
docker compose -f docker-compose.multinode-clickhouse.yml down -v
docker compose -f docker-compose.dev.yml up -d zookeeper kafka clickhouse
flox activate -- bash -c "DEBUG=1 python manage.py migrate_clickhouse"
hclexp introspect -host localhost -port 9000 -database posthog -node all \
  -exclude posthog/clickhouse/hcl/exclude.hcl -out -
```

`introspect` emits a leading `node {}` block; layer files carry none (`roles/**` has zero `^node "`), so
strip it when turning a dump into a layer. `exclude.hcl` will likely need entries for whatever the dev node
carries that the managed set omits — add each with a one-line reason, as the file's header requires.

**Composition — reuse first, measure, then decide.** The candidate stack is the union of the local layers:

```text
roles/shared  roles/ops/shared  roles/ops/local  roles/logs/local
roles/ai_events/shared  roles/ai_events/local
roles/auxiliary/shared  roles/auxiliary/local
roles/data/local
```

23 object names are defined in two of these layers, so composition is last-layer-wins and may not match
reality: `person` and `person_distinct_id2` are Distributed shims in `roles/ai_events/shared` but real
storage tables in `roles/data/local`; `ai_events` differs between `roles/ai_events/local` and
`roles/data/local`; `query_log_archive` differs between `roles/logs/local` and `roles/shared`; and the whole
`web_*`/`marketing_*` preaggregated family plus `hog_invocation_results`, `message_assets`,
`property_values_distributed`, `ingestion_warnings_v2_distributed`, `session_replay_features`,
`web_bot_definition{,_dict}`, `error_tracking_fingerprint_issue_state`,
`experiment_metric_events_preaggregated`, `conversion_goal_attributed_preaggregated` sit in both
`roles/auxiliary/shared` and `roles/data/local`. (`data/local` last is the right guess — on the real node
the storage table wins — but it is a guess.)

Decision rule, against `hclexp diff -left <composed stack> -right <dump>`:

- **no differences** → ship the stack as-is, zero new layer files;
- **small delta** → add `roles/single/local/` as a thin overlay, composed last, holding only the deltas;
- **large or contradictory** (e.g. the collisions resolve inconsistently) → make `roles/single/local/`
  self-contained, extracted from the dump, exactly as `roles/logs/local` already is. Document why in the
  manifest comment.

**Manifest entry**, then `gen-golden.sh local-single` + `gen-sql.sh`:

```hcl
role "all" {
  env "local-single" { layers = [ ... whichever the diff selects ... ] }
}
```

**`dump-live.sh`** — its `ROLES` table (role → host/port/db) is multinode-specific. Make it env-conditional:
`VERIFY_LIVE_ENV=local-single` selects a single `all localhost 9000 posthog` row. `check-live.sh` then picks
up role `all` for free once it derives roles from the manifest (item 3).

Wiring a CI gate for the single node is **out of scope** — `check.sh` already covers the new env's golden
and SQL freshness offline at zero cost, and a live gate would need its own workflow. Note it as a follow-up.

## Verification

```bash
HCL=posthog/clickhouse/hcl
export HCLEXP_BIN=$(which hclexp)          # v0.1.1-9-ge860af4 is already on $PATH here

# 3 — the manifest refactor must be a no-op for the eight existing nodes
git stash && bash $HCL/gen-golden.sh && bash $HCL/gen-sql.sh && git diff --stat   # baseline: clean
# after the refactor:
bash $HCL/gen-golden.sh && bash $HCL/gen-sql.sh
git diff --exit-code -- $HCL/golden $HCL/sql   # MUST be empty: same goldens, new plumbing
bash $HCL/check.sh                             # exit 0
bash $HCL/diff.sh                              # "no HCL changes" or only the local-single node
python $HCL/codegen/gen_migration.py --name probe   # exits 1 "no changes vs the goldens" — proves plan still runs

# 2 — CI binary path, locally
unset HCLEXP_BIN; hash -r; $HCL/bin/hclexp -version    # resolves via $PATH, no docker

# 4 — the single node
DUMP=$(VERIFY_LIVE_ENV=local-single bash $HCL/dump-live.sh)
hclexp diff -left <composed-stack> -right "$DUMP/local-single-all.hcl"   # drives the decision rule
bash $HCL/check-live.sh "$DUMP"        # after the golden lands: "no differences"
hclexp validate -manifest $HCL/manifest.hcl -env local-single -layer-root $HCL -strict-clusters

# and the multinode env still converges (the pin bump is the risk here)
tools/infra-scripts/clickhouse-multinode/start-multinode-clickhouse up
tools/infra-scripts/clickhouse-multinode/multinode-migration-smoke
```

Restore the environment afterwards: the multinode stack and the dev stack both bind `:9000`.

## Commits

Three, in order, each independently green:

1. `chore(clickhouse): bump hclexp to sha-e860af4 and run it as a binary in CI`
2. `chore(clickhouse): replace nodes+clusters with a committed manifest.hcl`
3. `feat(clickhouse): model the single-node local dev ClickHouse as local-single/all`
