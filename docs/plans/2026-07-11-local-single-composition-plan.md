# `local-single` pure-composition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `local-single` env compose from the deduplicated node-role layers and own no table of its own, deleting the 20k-line self-contained dump.

**Architecture:** Normalize each object that is currently declared in two role layers into a single `roles/coshared/<members>/` layer included by exactly the roles that host it, split the `person`/`person_distinct_id2` proxy into an ai_events-only sublayer that `local-single` omits, then point `local-single` at the deduped union. Every step preserves the resolved object set per env, so all goldens stay byte-identical.

**Tech Stack:** HCL layer files under `posthog/clickhouse/hcl/`, the pinned `hclexp` binary (`sha-e860af4`), the repo's `gen-golden.sh` / `gen-sql.sh` / `check.sh` scripts.

## Global Constraints

- **Invariant, checked after every task:** `git diff --exit-code -- posthog/clickhouse/hcl/golden posthog/clickhouse/hcl/sql` is **empty**. The refactor changes only source layers + the manifest, never a resolved golden. (hclexp emits each golden deterministically from the resolved object set, independent of which layer declared each object; the duplicate copies were verified to resolve identically.)
- **Tooling:** always `export HCLEXP_BIN=$(which hclexp)` first (v0.1.1-9-ge860af4, already on `$PATH`). Never edit files under `golden/` or `sql/` by hand — regenerate.
- **Every object moved in this plan is a Distributed table** (engine `distributed`, no `query = file(...)` body), so a move is a pure relocation of the `table "<name>" { ... }` block between `tables.hcl` files. No `sql/` files move.
- **Commits:** signed. In this environment husky signing is flaky and the pre-commit hook is slow; commit with `HUSKY=0 git -c commit.gpgsign=true -c user.signingkey="key::<pubkey>" commit`. Never `--no-verify` a push. Conventional-commit messages, no AI attribution.
- **Branch:** `pawel/chore/hcl-manifest-local-single` (PR #70166), stacked on `pawel/chore/hcl-manifest` (#70174).

## File Structure

New layers (each a directory with a single `tables.hcl`):

- `posthog/clickhouse/hcl/roles/coshared/qla/tables.hcl` — `query_log_archive` (Distributed → `sharded_query_log_archive`).
- `posthog/clickhouse/hcl/roles/coshared/aux_data/tables.hcl` — the 19 aux+data Distributed proxies.
- `posthog/clickhouse/hcl/roles/coshared/ai_events_data/tables.hcl` — `ai_events` (Distributed → `sharded_ai_events`).
- `posthog/clickhouse/hcl/roles/ai_events/ai_events_only/tables.hcl` — `person` + `person_distinct_id2` Distributed proxies.

Deleted at the end:

- `posthog/clickhouse/hcl/roles/single/local/tables.hcl` — the self-contained dump.

Modified: `posthog/clickhouse/hcl/manifest.hcl` (layer lists + the `role "all"` comment), the source layers the blocks move out of (`roles/shared/qla.hcl`, `roles/logs/local/tables.hcl`, `roles/auxiliary/shared/tables.hcl`, `roles/ai_events/{shared,local}/tables.hcl`, `roles/data/local/tables.hcl`), and the docs (`README.md`, `codegen/README.md`).

---

### Task 1: Promote `query_log_archive` to `roles/coshared/qla`

**Files:**

- Create: `posthog/clickhouse/hcl/roles/coshared/qla/tables.hcl`
- Modify: `posthog/clickhouse/hcl/roles/shared/qla.hcl` (remove the `query_log_archive` table block), `posthog/clickhouse/hcl/roles/logs/local/tables.hcl` (remove its `query_log_archive` block), `posthog/clickhouse/hcl/manifest.hcl` (add the layer to every env that hosts it)

**Interfaces:**

- Produces: a standalone `roles/coshared/qla` layer declaring exactly `query_log_archive`, includable by any role.

- [ ] **Step 1: Baseline is clean**

Run: `cd .claude/worktrees/pawel+chore+hcl-manifest-local-single && export HCLEXP_BIN=$(which hclexp) && HCL=posthog/clickhouse/hcl && git diff --exit-code -- $HCL/golden $HCL/sql`
Expected: no output, exit 0.

- [ ] **Step 2: Create the qla layer**

Create `roles/coshared/qla/tables.hcl` wrapping the exact `query_log_archive` table block (copy verbatim from `roles/shared/qla.hcl`) in a `database "posthog" { ... }`:

```hcl
database "posthog" {
  table "query_log_archive" {
    # ... exact block copied from roles/shared/qla.hcl ...
  }
}
```

- [ ] **Step 3: Remove the two source copies**

Delete the `query_log_archive` table block from `roles/shared/qla.hcl` and the `query_log_archive` block from `roles/logs/local/tables.hcl`. Leave everything else in those files untouched (`roles/shared/qla.hcl` keeps `ops_query_log_archive_mv` etc.).

- [ ] **Step 4: Add the layer to every env that hosts query_log_archive**

In `manifest.hcl`, append `"roles/coshared/qla"` to the `layers` of every env that currently resolves `query_log_archive`: all `ops`, `logs`, `ai_events`, `aux`, `sessions`, `sessionsv3`, `batch_exports`, and `data` envs. Every env that lists `"roles/shared"` gets `"roles/coshared/qla"` added; `logs`'s `local` env (which lists only `"roles/logs/local"`) also gets it. Example for `ops`:

```hcl
role "ops" {
  env "local"   { layers = ["roles/shared", "roles/coshared/qla", "roles/ops/shared", "roles/ops/local"] }
  env "dev"     { layers = ["roles/shared", "roles/coshared/qla", "roles/ops/shared", "roles/ops/dev"] }
  env "prod-us" { layers = ["roles/shared", "roles/coshared/qla", "roles/ops/shared", "roles/ops/prod", "roles/ops/prod-us"] }
  env "prod-eu" { layers = ["roles/shared", "roles/coshared/qla", "roles/ops/shared", "roles/ops/prod", "roles/ops/prod-eu"] }
}
```

And `logs` `local`: `layers = ["roles/logs/local", "roles/coshared/qla"]`.

Leave the `role "all"` (local-single) env alone in this task — it still points at `roles/single/local`, which still has its own `query_log_archive`; Task 5 handles it.

- [ ] **Step 5: Regenerate and assert the invariant**

Run: `bash $HCL/gen-golden.sh && bash $HCL/gen-sql.sh && git diff --exit-code -- $HCL/golden $HCL/sql && bash $HCL/check.sh`
Expected: `git diff` empty (exit 0), `check.sh` exit 0. If a golden moved, the qla block copied into `roles/coshared/qla` differs from a source copy — reconcile so both original defs are byte-identical to the promoted one (the logs/local copy was verified identical to shared's).

- [ ] **Step 6: Commit**

```bash
HUSKY=0 git -c commit.gpgsign=true -c user.signingkey="key::<pubkey>" commit -q -am "chore(clickhouse): promote query_log_archive to a coshared/qla layer"
```

---

### Task 2: Deduplicate the `ai_events` proxy into `roles/coshared/ai_events_data`

**Files:**

- Create: `posthog/clickhouse/hcl/roles/coshared/ai_events_data/tables.hcl`
- Modify: `roles/ai_events/local/tables.hcl` (remove `ai_events`), `roles/data/local/tables.hcl` (remove `ai_events`), `manifest.hcl`

**Interfaces:**

- Consumes: nothing from Task 1.
- Produces: `roles/coshared/ai_events_data` declaring exactly `ai_events` (Distributed → `sharded_ai_events`), included by ai_events + data.

- [ ] **Step 1: Confirm the two copies are identical**

Run a block-compare of `ai_events` in `roles/ai_events/local/tables.hcl` vs `roles/data/local/tables.hcl`.
Expected: identical (verified: both Distributed → `sharded_ai_events`). If they differ, stop and reconcile against `golden/local-ai_events.hcl` (the live winner).

- [ ] **Step 2: Create the layer**

Create `roles/coshared/ai_events_data/tables.hcl` with `database "posthog" { table "ai_events" { ...verbatim... } }`.

- [ ] **Step 3: Remove both source copies** from `roles/ai_events/local/tables.hcl` and `roles/data/local/tables.hcl`.

- [ ] **Step 4: Wire the layer in `manifest.hcl`**

Add `"roles/coshared/ai_events_data"` to the ai_events envs that include `roles/ai_events/local` (env `local`) and to `data` `local`. `ai_events` `prod-us`/`prod-eu` include `roles/ai_events/prod` (not `local`) — check whether they resolve `ai_events`; if `golden/prod-*-ai_events.hcl` contains it, add the layer there too, otherwise leave them.

```hcl
role "ai_events" { env "local" { layers = ["roles/shared", "roles/coshared/qla", "roles/ai_events/shared", "roles/ai_events/local", "roles/coshared/ai_events_data"] } ... }
role "data"      { env "local" { layers = ["roles/shared", "roles/coshared/qla", "roles/data/local", "roles/coshared/ai_events_data"] } }
```

- [ ] **Step 5: Regenerate and assert the invariant** — same command as Task 1 Step 5.

- [ ] **Step 6: Commit** — `... commit -am "chore(clickhouse): deduplicate the ai_events proxy into a coshared layer"`.

---

### Task 3: Deduplicate the 19 aux+data proxies into `roles/coshared/aux_data`

**Files:**

- Create: `posthog/clickhouse/hcl/roles/coshared/aux_data/tables.hcl`
- Modify: `roles/auxiliary/shared/tables.hcl` (remove 19 blocks), `roles/data/local/tables.hcl` (remove 19 blocks), `manifest.hcl`

**Interfaces:**

- Produces: `roles/coshared/aux_data` declaring exactly these 19 objects, included by aux + data.

The 19 objects: `web_stats_preaggregated`, `web_stats_dimensional_preaggregated`, `web_stats_frustration_preaggregated`, `web_goals_preaggregated`, `web_bounces_dimensional_preaggregated`, `web_vitals_paths_preaggregated`, `marketing_touchpoints_preaggregated`, `marketing_costs_preaggregated`, `marketing_conversions_preaggregated`, `experiment_metric_events_preaggregated`, `conversion_goal_attributed_preaggregated`, `web_bot_definition`, `web_bot_definition_dict`, `session_replay_features`, `property_values_distributed`, `message_assets`, `ingestion_warnings_v2_distributed`, `hog_invocation_results`, `error_tracking_fingerprint_issue_state`.

- [ ] **Step 1: Pick the authoritative copy per object**

For each of the 19, the `auxiliary/shared` copy uses `extend = "_..._columns"` (the DRY form) while `data/local` inlines columns. Both were verified to **resolve identically** in the goldens. Use the `auxiliary/shared` form as the single definition — but that form depends on the `_..._columns` column-set macros. Check where those macros are defined (grep `_web_stats_preaggregated_columns` etc.): if they live in `auxiliary/shared`, the `aux_data` layer must be able to resolve them, so either (a) move the macro definitions into `roles/coshared/aux_data` too, or (b) keep macros in a layer `aux_data`'s consumers already include. Confirm by regeneration (Step 4).

- [ ] **Step 2: Create the layer** — `roles/coshared/aux_data/tables.hcl` with `database "posthog" { ... 19 blocks ... }` plus any column-set macros they reference.

- [ ] **Step 3: Remove the 19 blocks** from `roles/auxiliary/shared/tables.hcl` and `roles/data/local/tables.hcl` (and the now-unused inline columns in data/local).

- [ ] **Step 4: Wire the layer in `manifest.hcl`**

Add `"roles/coshared/aux_data"` to `aux` `local`/`prod-us`/`prod-eu` and `data` `local`.

- [ ] **Step 5: Regenerate and assert the invariant** — same command. A moved golden here means a real drift bug in one copy (the resolved forms were verified identical for a sample; if a non-sampled object differs, reconcile against the live winner — `golden/local-data.hcl` for the single node — and note it in the commit body).

- [ ] **Step 6: Commit** — `... commit -am "chore(clickhouse): deduplicate 19 aux+data proxies into a coshared layer"`.

---

### Task 4: Split `person` / `person_distinct_id2` proxies into an ai_events-only sublayer

**Files:**

- Create: `posthog/clickhouse/hcl/roles/ai_events/ai_events_only/tables.hcl`
- Modify: `roles/ai_events/shared/tables.hcl` (remove the two proxy blocks), `manifest.hcl`

**Interfaces:**

- Produces: `roles/ai_events/ai_events_only` declaring the two Distributed proxies; included by ai_events envs, **excluded** from `local-single` so the data storage tables win there.

- [ ] **Step 1: Create the sublayer** — move the `person` and `person_distinct_id2` **proxy** blocks (Distributed → cluster `posthog`, `remote_table` = themselves) verbatim out of `roles/ai_events/shared/tables.hcl` into `roles/ai_events/ai_events_only/tables.hcl` (`database "posthog" { ... }`). The `data/local` **storage** copies stay put.

- [ ] **Step 2: Wire the sublayer into ai_events envs** — add `"roles/ai_events/ai_events_only"` to every ai_events env that currently resolves the proxies (those that include `roles/ai_events/shared`: `local`, `prod-us`, `prod-eu`; confirm against `golden/*-ai_events.hcl`).

- [ ] **Step 3: Regenerate and assert the invariant** — same command. The ai_events goldens must be unchanged (proxy now from the sublayer).

- [ ] **Step 4: Commit** — `... commit -am "chore(clickhouse): move person proxies to an ai_events-only sublayer"`.

---

### Task 5: Rebuild `local-single` as the deduped union; delete the dump

**Files:**

- Modify: `manifest.hcl` (`role "all"` layer list + comment)
- Delete: `posthog/clickhouse/hcl/roles/single/local/tables.hcl`
- Regenerate: `golden/local-single-all.hcl`, `sql/local-single-all.sql`

**Interfaces:**

- Consumes: all four new layers from Tasks 1-4.

- [ ] **Step 1: Set the composition**

Replace the `role "all"` block. The `layers` is the hand-deduped union of the local layers of every role the single node hosts (ops, logs, ai_events, aux, sessions, data), each layer listed once, **excluding** `roles/ai_events/ai_events_only` (so storage `person` wins). Draft:

```hcl
role "all" {
  env "local-single" { layers = [
    "roles/shared",
    "roles/coshared/qla",
    "roles/ops/shared", "roles/ops/local",
    "roles/logs/local",
    "roles/ai_events/shared", "roles/ai_events/local",
    "roles/auxiliary/shared", "roles/auxiliary/local",
    "roles/coshared/aux_data",
    "roles/coshared/ai_events_data",
    "roles/data/local",
  ] }
}
```

Replace the stale "cannot be composed / loader rejects redeclaration" comment with a short note: single node = composition of every hosted role's layers; the ai_events-only sublayer (person/pdi2 proxies) is deliberately excluded so the data storage tables win.

- [ ] **Step 2: Delete the dump** — `git rm posthog/clickhouse/hcl/roles/single/local/tables.hcl` (and `rmdir` the empty dirs).

- [ ] **Step 3: Regenerate**

Run: `bash $HCL/gen-golden.sh local-single && bash $HCL/gen-sql.sh`
Then assert the composed golden equals the committed self-contained one:
`git diff --exit-code -- $HCL/golden/local-single-all.hcl $HCL/sql/local-single-all.sql`
Expected: **empty** — the composition resolves to the same node the dump captured. If it differs, diff the composed output against the golden to find the missing/extra object and fix the union (a missing layer, or an object still duplicated).

- [ ] **Step 4: Full gate**

Run: `git diff --exit-code -- $HCL/golden $HCL/sql && bash $HCL/check.sh && hclexp validate -manifest $HCL/manifest.hcl -env local-single -layer-root $HCL -strict-clusters && python $HCL/codegen/gen_migration.py --name probe --out -`
Expected: diff empty; check.sh exit 0; validate passes; gen_migration prints "No DDL generated".

- [ ] **Step 5: Commit** — `... commit -am "feat(clickhouse): compose local-single from node-role layers, drop the dump"`.

---

### Task 6: Update docs and the exclude/dump plumbing

**Files:**

- Modify: `posthog/clickhouse/hcl/README.md`, `posthog/clickhouse/hcl/codegen/README.md`, `posthog/clickhouse/hcl/exclude-local-single.hcl` (header only if wording references the self-contained layer), `docs/plans/2026-07-11-local-single-composition.md` (mark done)

**Interfaces:**

- Consumes: the final layer topology from Task 5.

- [ ] **Step 1: README tree** — in `README.md`, replace the `roles/single/local/` tree entry with the `roles/coshared/*` and `roles/ai_events/ai_events_only/` entries and a one-line note that `local-single` is a pure composition.

- [ ] **Step 2: codegen/README** — the "Extracting a self-contained layer from a live node" section still documents the `roles/logs/local` case (valid); adjust any sentence that implied `local-single` is self-contained.

- [ ] **Step 3: Verify docs lint** — `pnpm exec markdownlint-cli2 --config .config/.markdownlint-cli2.jsonc "posthog/clickhouse/hcl/README.md" "posthog/clickhouse/hcl/codegen/README.md"` then `pnpm exec oxfmt --write ...` the same files.

- [ ] **Step 4: Final preflight** — `hogli ci:preflight` (expect only the staleness advisory, 0 failures).

- [ ] **Step 5: Commit + push** — `... commit -am "chore(clickhouse): document local-single composition"` then `git push` (updates PR #70166; pre-push runs ci:preflight --strict).

---

## Self-Review

- **Spec coverage:** query_log_archive promotion (Task 1), 19 aux+data dedup (Task 3), ai_events dedup (Task 2), person/pdi2 split (Task 4), local-single composition + dump deletion (Task 5), docs (Task 6), invariant verification (every task Step "assert the invariant"). All spec sections covered.
- **Placeholder scan:** the only `<...>` are `key::<pubkey>` (the real key is in the signing memory) and per-object blocks that are "copy verbatim from source" (exact source named) — not TBDs.
- **Ordering risk:** addressed by the structural fact in Global Constraints (golden = f(resolved set)); each task re-asserts `git diff` empty, so any surprise is caught at that task's Step 5, not downstream.
- **Open risk carried into execution:** Task 3 Step 1 (column-set macro resolution for the `extend` form) — resolved empirically at Step 4; fallback is to inline the columns in `aux_data` (still one definition).
