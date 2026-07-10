# `local-single` as a pure composition of node-role layers

## Context

The `local-single` env (role `all`) models the one ClickHouse node `bin/start` runs, where
`migration_tools.py` routes every migration to `NodeRole.ALL`.
The shipped implementation (branch `pawel/chore/hcl-manifest-local-single`, PR #70166) models it as a
**self-contained** layer `roles/single/local/tables.hcl` — a 20k-line dump extracted from a migrated
node — on the theory that composition could not reproduce the node.

That theory is wrong.
`hclexp` supports `override = true`; it rejects a redeclaration only when the winning layer does not
mark itself (`table "query_log_archive" redeclared without override = true`).
And the objects that "conflict" across role layers are almost all the **same table declared twice** —
accidental duplication, some with cosmetic drift (`extend = "_..._columns"` in one copy, the columns
inlined in the other).

So `local-single` should be what its name says: a composition of every node role's layers, owning no
table of its own. Getting there means normalizing the duplicated declarations so each object lives in
exactly one layer, included by exactly the roles that host it.

## Goal / non-goals

- **Goal:** `local-single` = `compose(union of node-role local layers)`, zero tables of its own.
  Delete `roles/single/local/tables.hcl`.
- **Goal:** each shared/distributed table is declared once, in a layer included by the roles that host it.
- **Hard invariant:** the 19 existing goldens stay byte-for-byte identical, _except_ where dedup exposes
  a genuine drift bug (two copies that resolve differently) — those are reconciled against the live
  single-node schema and documented per object.
- **Invariant:** the newly-composed `golden/local-single-all.hcl` equals the current self-contained one
  (which matches the live node).
- **Non-goal:** changing any live schema or migration. This is an HCL-layer refactor only.

## Findings

### Conflict taxonomy (23 objects declared in ≥2 union layers)

**A. Accidental duplication — dedup into one layer (21):**

| Group                    | Objects                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  | Both copies                                                                                                                  |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| aux + data (19)          | `web_stats_preaggregated`, `web_stats_dimensional_preaggregated`, `web_stats_frustration_preaggregated`, `web_goals_preaggregated`, `web_bounces_dimensional_preaggregated`, `web_vitals_paths_preaggregated`, `marketing_touchpoints_preaggregated`, `marketing_costs_preaggregated`, `marketing_conversions_preaggregated`, `experiment_metric_events_preaggregated`, `conversion_goal_attributed_preaggregated`, `web_bot_definition`, `web_bot_definition_dict`, `session_replay_features`, `property_values_distributed`, `message_assets`, `ingestion_warnings_v2_distributed`, `hog_invocation_results`, `error_tracking_fingerprint_issue_state` | Distributed proxy in `auxiliary/shared` (via `extend`) and `data/local` (inlined). Same engine → cluster `aux`, `sharded_*`. |
| ai_events + data (1)     | `ai_events`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              | Identical Distributed → `sharded_ai_events`, in `ai_events/local` and `data/local`.                                          |
| all roles incl. logs (1) | `query_log_archive`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                      | Identical Distributed → `sharded_query_log_archive`, in `roles/shared/qla.hcl` and `roles/logs/local`.                       |

**B. Genuine proxy-vs-storage collision — structural split (2):**

`person`, `person_distinct_id2`: a Distributed **proxy** (`remote_table` = itself) in `ai_events/shared`,
and the real `replicated_replacing_merge_tree` **storage** table in `data/local`.
Same name, different object. On a single node only the storage can exist (which is what the live node
runs — the proxy's `CREATE ... IF NOT EXISTS` is a no-op).

### Placement (which goldens hold each object) — drives layer membership

| Object group                     | Present in goldens                            | ⇒ dedup target included by                        |
| -------------------------------- | --------------------------------------------- | ------------------------------------------------- |
| aux+data preagg family           | `*-aux`, `local-data`                         | aux (all envs) + data (local)                     |
| `ai_events` proxy                | `*-ai_events`, `local-data`                   | ai_events + data                                  |
| `query_log_archive`              | ops, ai_events, aux, sessions, data, **logs** | a shared qla layer every role incl. logs includes |
| `person` / `person_distinct_id2` | `*-ai_events` (proxy), `local-data` (storage) | proxy → ai_events-only sublayer; storage → data   |

Plain `roles/shared` is **not** a valid target for the aux+data or ai_events+data groups: it is included
by ops/ai_events/sessions too, so moving objects there would add tables to those goldens.

### `hclexp` behavior to confirm during implementation

- Whether a repeated identical layer _path_ in one stack is de-duplicated or errors (affects whether the
  `local-single` layer list may list overlapping stacks or must be a hand-deduped union).
- Whether `override = true` errors when the stack has nothing to override (only relevant if the person
  sublayer split fails and we fall back to an override layer).

## Design

### 1. Co-tenant shared layers

Introduce layers keyed by the set of roles that co-host their objects:

- `roles/coshared/aux_data/` — the 19 aux+data Distributed proxies, in `extend` form (the DRY source).
- `roles/coshared/ai_events_data/` — the `ai_events` Distributed proxy.
- `roles/coshared/qla/` — `query_log_archive`, promoted out of `roles/shared/qla.hcl` into its own
  standalone layer (the `ops_query_log_archive_mv` and `custom_metrics*` content stays in `roles/shared`).

Each object is removed from its current two homes and declared once here.

### 2. Wire roles to include the co-tenant layers

Update `manifest.hcl` layer lists so resolved compositions are unchanged:

- `aux` (local/dev/prod-\*): add `roles/coshared/aux_data`; remove the 19 from `auxiliary/shared`.
- `data` (local): add `roles/coshared/aux_data` + `roles/coshared/ai_events_data`; remove the 19 + `ai_events` from `data/local`.
- `ai_events` (local/dev/prod-\*): add `roles/coshared/ai_events_data`; remove `ai_events` from `ai_events/local`.
- `query_log_archive`: every role currently getting it via `roles/shared` (ops, ai_events, aux, sessions,
  data) plus `logs` now include `roles/coshared/qla`; `logs/local` drops its own copy; the declaration is
  removed from `roles/shared/qla.hcl`.

Every edit is followed by `gen-golden.sh <env>` + `git diff` — the golden must not move (see invariant).

### 3. `person` / `person_distinct_id2` — structural split, no override

- Move the two **storage** tables into their own file within the `data` layer (e.g. `data/local/person.hcl`).
- Move the two **proxy** tables into a new `ai_events`-only sublayer (e.g. `roles/ai_events/ai_events_only/`)
  that the `ai_events` local/dev/prod envs include, but that `local-single` does **not** list.
- `local-single` composes the storage from `data` and never sees the proxy → no collision, no override,
  no unique table.
- Fallback (only if a golden won't hold): a minimal `roles/single/local` overlay redeclaring the two with
  `override = true`. This is the sole scenario where `local-single` owns any content.

### 4. `local-single` manifest entry

```hcl
role "all" {
  env "local-single" { layers = [ <deduped union of every hosted role's local layers> ] }
}
```

No `roles/single/local/tables.hcl`. Delete it, `golden/local-single-all.hcl` is regenerated from the
composition, `sql/local-single-all.sql` too.

## Verification

Offline, against `hclexp sha-e860af4`:

```bash
HCL=posthog/clickhouse/hcl
export HCLEXP_BIN=$(which hclexp)
bash $HCL/gen-golden.sh && bash $HCL/gen-sql.sh
git diff --exit-code -- $HCL/golden $HCL/sql   # 19 goldens unchanged; local-single regenerated identical
bash $HCL/check.sh                              # exit 0, all envs incl local-single
hclexp validate -manifest $HCL/manifest.hcl -env local-single -layer-root $HCL -strict-clusters
python $HCL/codegen/gen_migration.py --name probe --out -   # "No DDL generated"
```

Extra check per dedup: confirm the two pre-dedup copies resolved identically by comparing the relevant
resolved goldens (e.g. the aux+data proxy columns in `golden/local-data.hcl` vs `golden/*-aux.hcl`). A
mismatch is a real drift bug — reconcile against the live single-node schema and note it.

## Sequencing

Per the "full refactor, replace PR" decision:

- Replace the `local-single` commit on `pawel/chore/hcl-manifest-local-single` (PR #70166): drop the
  self-contained `roles/single/local/tables.hcl` dump; add the co-tenant layers + composition.
- Keep the manifest.hcl + hclexp cleanup PR #70174 (base) unchanged.
- Land the refactor as a sequence of golden-preserving commits (one per dedup group is reviewable and
  each is independently green), then the final `local-single` composition + dump deletion.

## Resolved decisions

1. Co-tenant layers use the `roles/coshared/<members>/` scheme.
2. `query_log_archive` is promoted into its own standalone `roles/coshared/qla/` layer.
3. `person` / `person_distinct_id2` use the **sublayer split** (no override); the override overlay is not used.
