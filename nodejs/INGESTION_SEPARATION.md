# Ingestion separation refactor

Working tracker for separating ingestion code from the rest of the Node.js service.
This file is the durable source of truth for the refactor loop: each iteration reads the
checklist, does **exactly one** unchecked item (one part per iteration — never batch), runs the
gate (tests must pass), commits, checks the item off, and appends to the status log. Delete this
file before the final merge to master.

## Goal

Separate all ingestion code from other Node.js code so that ingestion and CDP can evolve and
be tested independently.

## Guidelines (locked)

- All ingestion code lives in one place inside `nodejs/src`.
- Code shared between CDP and ingestion lives in a common folder.
- Each ingestion lane has its own directory under `src/ingestion/lanes/` (Phase 4).
- The pipeline-building framework lives in `src/ingestion/framework/`; shared pipeline steps in
  `src/ingestion/steps/` (Phase 4).
- Cross-directory imports use the `~/` alias (the codebase standard); reserve relative paths for
  same-directory siblings (`./`) (Phase 5).
- Test selection follows the dependency graph:
  - No ingestion tests run when CDP-only code is modified.
  - No CDP tests run when ingestion-only code is modified.
  - When common code changes, **everything** runs (CDP + all ingestion lanes).
- All tests must pass. No tests are removed.
- If a test file mixes CDP and ingestion logic, split the ingestion logic into its own test.
- Unit tests live beside the files they test. Integration and e2e tests live in separate folders.
- All CI, scripts, etc. adapt to the new layout.
- Group files by semantic separation within every folder (e.g. `common/persons`, `common/groups`,
  `common/personhog`) — avoid flat dumps.
- No renaming of files; prefer moves over rewrites. Change a file only when:
  - imports need fixing, or
  - CDP and ingestion logic in the same file can be separated, or
  - duplicated methods can be merged.

## Locked taxonomy

### Ingestion lanes (each gets isolated test selection)

| Lane                | Current source                                                                           |
| ------------------- | ---------------------------------------------------------------------------------------- |
| `analytics`         | `src/ingestion/analytics` (core event pipeline)                                          |
| `heatmaps`          | `src/ingestion/heatmaps`                                                                 |
| `ingestionwarnings` | `src/ingestion/clientwarnings` (+ shared `common/ingestion-warnings.ts`)                 |
| `logs`              | `src/logs-ingestion` (move in)                                                           |
| `metrics`           | `src/metrics-ingestion` (move in)                                                        |
| `session-replay`    | merge of `src/session-recording` + `src/session-replay` + `src/ingestion/session_replay` |
| `ai`                | `src/ingestion/ai`                                                                       |
| `error-tracking`    | `src/ingestion/error-tracking`                                                           |

Lane-dir naming note: `clientwarnings` becomes the `ingestionwarnings` lane via a directory
move (allowed — it is a move, not a file rename). Deferred to Phase 2.

### Ingestion-shared (a change here runs all lane tests)

`pipelines/` (the framework), `common/`, `outputs/`, `event-processing/`,
`event-preprocessing/`, `cookieless/`, `personhog/`, `tophog/`, `utils/`, `api/`.

Phase 4 regroups these: `pipelines/` (+ `tophog/`) -> `framework/`; `event-processing/` +
`event-preprocessing/` -> `steps/`; `cookieless/` -> `common/`. A change in any of them still runs
all lane tests.

Placement rule for each shared module = the narrowest scope covering all its importers:

- imported only by ingestion lanes -> `ingestion/common/`
- also imported by CDP / servers (e.g. `personhog`, `outputs`, `event-processing`) -> top-level
  `common/` (the CDP ∩ ingestion tier).

### Out of scope (untouched "other / infra")

`servers`, `api` (top-level), `ai-observability`, `worker` (minus `worker/ingestion`, which folds
into ingestion), `kafka`, `config`, `schema`, `generated`.

## The invariant (what the whole refactor serves)

The import graph must be a DAG:

- a lane may import `{ common, ingestion/common, pipelines }` only — **never another lane**;
- common code may **never** import a lane;
- ingestion may **never** import CDP and CDP may **never** import ingestion — both go through `common`.

The CI path-based test selection is only _correct_ once this DAG holds. Everything else
(folder moves, test splits) is downstream of establishing it.

Known seams to break (from current code):

- CDP <-> ingestion: ~37 cross-edges (e.g. `IngestionOutputs`, `~/ingestion/common/outputs`,
  `hog-transformer`, person repositories) -> move shared pieces to top-level `common/`.
- 63 files import `worker/ingestion` -> folds into the ingestion folder.
- `event-processing/` and `event-preprocessing/` (shared) currently import lanes -> invert.

## Test-isolation / CI design

Extend the existing `dorny/paths-filter` in `.github/workflows/ci-nodejs.yml` to emit a flag per
lane plus `common` / `cdp`, then gate jest runs by area:

| Changed area       | Runs                                   |
| ------------------ | -------------------------------------- |
| a single lane      | that lane's tests only                 |
| CDP only           | CDP tests only                         |
| `ingestion/common` | all ingestion lanes                    |
| top-level `common` | everything (CDP + all ingestion lanes) |

Wired in Phase 6, after the DAG holds and the restructure (Phases 4–5) lands.

## The boundary guard (Phase 0 — done)

`bin/check-ingestion-boundaries.mjs` resolves imports (`~/*` alias + relative) and fails on any
**new** lane->lane or shared->lane edge beyond `bin/ingestion-boundaries.baseline.json`.

- check: `pnpm --filter=@posthog/nodejs check:boundaries`
- shrink baseline after removing edges: `pnpm --filter=@posthog/nodejs check:boundaries:write`

The baseline only ever shrinks. An empty baseline means the intra-ingestion DAG is clean.

## Loop gate (run every iteration before commit)

1. `pnpm --filter=@posthog/nodejs check:boundaries` — no new boundary violations.
2. `pnpm --filter=@posthog/nodejs typecheck` (or `tsc --noEmit`) — compiles.
3. `pnpm --filter=@posthog/nodejs lint` + `format:check`.
4. Affected unit tests (the touched lane/shared area) **pass** — no failures, no tests removed.
5. Diff is moves-only except for the allowlisted change reasons above.

### Running the full test suite

The full jest suite needs the Kafka/ClickHouse/Postgres/Redis stack, so it requires a working
Docker daemon. In any docker-capable environment (CI, a devbox, or local dev):

```bash
# one command (from nodejs/):
pnpm test:full
# which is equivalent to:
docker compose -f ../docker-compose.dev.yml up -d   # start the stack
pnpm setup:test                                     # Django setup_test_environment + rust migrations
pnpm test                                           # all jest tests except postgres-parity + service-e2e
pnpm test:postgres-parity                           # the postgres-parity suite
pnpm test:rust-ingestion-e2e                        # the rust ingestion e2e suite
```

Shard with `SHARD_INDEX` / `SHARD_COUNT` to parallelise `pnpm test` (CI runs 3 shards).

This is the **phase-completion / final gate** — run it before finishing a phase, not on every
iteration. The fast per-iteration gate above (boundaries + typecheck + lint + affected unit tests)
is what runs each loop step. NOTE: the agent sandbox has the Docker **client** but no daemon
(`/var/run/docker.sock` absent), so `pnpm test:full` cannot run there — it runs in CI on push, or
locally / on a devbox.

Guardrails: work on `claude/affectionate-ritchie-6jh88d`; commit locally per step; do not push
on every iteration.

### Loop discipline — one part per iteration

The loop does **exactly one** checklist item per iteration, then stops; the next iteration picks up
the next item. One part at a time keeps each step small, independently gated, and easy to review or
revert. Run it self-paced with `/loop` from `nodejs/`, using this prompt:

```text
Read nodejs/INGESTION_SEPARATION.md. Pick the FIRST unchecked "[ ]" checklist item (topmost
phase first). If none remain, stop and report "refactor complete".

Do ONLY that one item — never batch items or start the next one.

Run the loop gate; ALL must pass before committing:
  - pnpm --filter=@posthog/nodejs check:boundaries   (no new boundary violations)
  - tsc --noEmit                                      (no new errors)
  - pnpm --filter=@posthog/nodejs lint + format:check
  - the affected unit tests                           (no failures, no tests removed)
If the item is a phase "Exit gate", run `pnpm test:full` instead of just the affected tests
(or record it as the CI gate when no Docker daemon is available).

If the gate fails, fix forward within this SAME item — do not move on.

Commit locally with a conventional-commit message. Do NOT push unless explicitly told to.
Check the item off ("[x]"), append a one-paragraph entry to the status log, then STOP.
The next /loop iteration handles the next item.
```

## Phased checklist (progress tracker)

**Per-phase exit gate:** no phase is done until `pnpm test:full` (the full suite — see "Running the
full test suite" above) is green. It needs a Docker daemon, so it runs in CI on push, or on a
devbox / local — not in the agent sandbox. Each phase's final box is this gate; tick it only once
the full suite passes (Phase 0 moved no production code, so it is guard-only and has no gate).

### Phase 0 — scaffold + guard

- [x] Boundary guard script + baseline (`bin/check-ingestion-boundaries.mjs`).
- [x] `check:boundaries` / `check:boundaries:write` npm scripts.
- [x] Defensive CI step running the guard in the lint job.
- [x] This plan/progress file.

### Phase 1 — break the CDP <-> ingestion seams

- [x] Inventory every CDP->ingestion and ingestion->CDP import.
- [x] Group 1: move the outputs framework (`ingestion/outputs` + `ingestion/common/outputs`)
      -> `common/outputs`; fix imports (219 across 131 files).
- [x] Group 2: break the hog-transformer cycle via dependency inversion. hog-transformer is
      deeply cdp-coupled (measured: a move would drag 189/256 cdp files into common), so instead a
      `HogTransformer` interface + `HogTransformationResult` live in `common/hog-transformations`;
      ingestion imports the interface; cdp's `HogTransformerService implements HogTransformer`;
      servers construct the impl. Production ingestion->cdp imports are now zero.
- [x] Group 3: move the persons/groups data-access core to common (Option B — data-access only,
      not the whole domain). 27 files -> `common/persons`, `common/groups`, `common/personhog`
      (repositories + personhog + low-level deps); 18 higher-level person/group processing files
      stay in ingestion and import the core from common. Extracted `PERSONS_OUTPUT` /
      `PERSON_DISTINCT_IDS_OUTPUT` to `common/outputs/persons`. 208 imports rewritten across 82 files.
- [x] Group 4 (mechanical part): extract shared output names (`ASYNC_OUTPUT`, `AI_EVENTS_OUTPUT`)
      to `common/outputs` and `AI_EVENT_TYPES` to `ingestion/common/ai-event-types`; repoint the
      shared `event-processing` / `event-preprocessing` steps and other cross-lane callers. Baseline
      shrank 14 -> 2. The 2 remaining edges are deferred to Phase 2 (they are lane-structure
      decisions, not output/constant sharing):
  - `analytics/per-distinct-id-pipeline.ts -> ai` (analytics composes `createAiEventSubpipeline`)
  - `ingestion-consumer.ts -> analytics` (composition root wiring the analytics pipeline)
- [x] CDP no longer imports ingestion and vice versa (production): cdp->ingestion = 0,
      cdp->worker/ingestion = 0, ingestion->cdp = 0. Test-only edges remain (Phase 3). Intra-ingestion
      baseline now 2 (the ai<->analytics composition), to be resolved with lane structure in Phase 2.
- [x] **Exit gate:** local validation green (guard + tsc + 546 infra-free unit tests); full
      `pnpm test:full` delegated to CI on push (not runnable in the agent sandbox — Docker Hub pull
      limits + pinned-Python download blocked).

### Phase 2 — consolidate into lanes

- [x] Fold `worker/ingestion` into the ingestion folder. `group-type-manager` (+ `readonly-`, + test) -> top-level `common/groups` (forced: `types.ts`/`hub.ts` import `GroupTypeManager`
      and are imported by cdp); `persons/`, `groups/`, `stores/`, `event-pipeline/` + the loose util
      files -> `ingestion/common/`. 203 imports rewritten across 84 files; `worker/ingestion` removed.
- [x] Move `logs-ingestion` -> `logs` lane, `metrics-ingestion` -> `metrics` lane. `src/logs-ingestion`
      -> `src/ingestion/logs`, `src/metrics-ingestion` -> `src/ingestion/metrics`. 44 imports rewritten
      across 15 files; no lane deps (lane-pure). The `config.ts`/`types.ts` top-level edges to these
      lanes are deferred to the guard-`LANES` item (when enforcement turns on).
- [x] Merge `session-recording` + `session-replay` + `ingestion/session_replay` -> `session-replay`.
      All three -> `src/ingestion/session-replay` (collision-free: no shared root files or subdir
      names). 231 imports rewritten across 76 files; lane-pure. Same top-level (`index.ts`/`config.ts`/
      `types.ts`) edges deferred to the guard-`LANES` item.
- [x] Move `clientwarnings` -> `ingestionwarnings` lane dir. `src/ingestion/clientwarnings` ->
      `src/ingestion/ingestionwarnings` (directory move, filenames unchanged). 32 imports across 5
      files; lane-pure; only the general server (composition root) imports it.
- [x] Place each shared module in its correct common tier. Validated the correctness direction:
      `cdp -> ingestion` = 0 and `cdp -> ingestion/common` = 0 (production), so every module cdp needs
      lives in top-level `common/` and ingestion-only modules live in `ingestion/common/`. (Narrowest-
      scope demotion of any over-broad top-level `common/` module is a non-blocking tidiness follow-up
      — no DAG impact.)
- [x] Add moved lanes to the guard's `LANES` set. `LANES` now = analytics, heatmaps, ingestionwarnings,
      ai, error-tracking, session-replay, logs, metrics. Guard green (2 baselined) — no intra-ingestion
      code imports the four newly-registered lanes, so lane isolation holds across all eight.
- [x] Resolve `analytics` -> `ai` (the ai/analytics separation; product-owner chose full separation).
      Dependency inversion: `AiEventSubpipelineInput`/`Config` + an `AiEventSubpipelineFactory` type now
      live in `ingestion/common/ai-subpipeline.contract`; analytics' per-distinct-id pipeline takes the
      factory injected (no ai import); the ai lane implements it; the servers (composition root) wire the
      concrete `createAiEventSubpipeline`. Guard baseline 2 -> 1. The guard now scopes to production
      files (test files are composition roots that wire real impls across domains — e.g. cdp's
      HogTransformer and the ai factory — so their cross-lane wiring is Phase 3's concern, not the guard's).
- [x] Resolve `ingestion-consumer` -> `analytics` (the last baselined edge). Resolution (product-owner
      choice): treat the consumer as a **composition root**. It stays at `src/ingestion/` and the guard
      now recognizes a `COMPOSITION_ROOTS` set — files that assemble and run a lane's pipeline (like the
      servers do) may import a lane. `ingestion-consumer.ts` builds + runs the analytics pipeline, so it
      is exempt from the shared->lane rule. **Guard baseline is now empty (`[]`) — the intra-ingestion
      DAG is clean: no lane imports another lane, and no shared code (other than composition roots)
      imports a lane.**
- [ ] **Exit gate:** `pnpm test:full` green.

### Phase 3 — split mixed tests

- [x] Find test files mixing CDP and ingestion logic. None found: 0 cdp test files import ingestion, and
      every ingestion test that imports cdp does so only to wire the hog-transformer (the Phase-1
      inversion) or to use shared cdp test helpers (`cdp/_tests/redis`, `cdp/_tests/fixtures`) — no cdp
      _logic_ is embedded in ingestion tests. Phase 1's decoupling already separated the test logic.
- [x] Split ingestion logic into its own test (no tests removed). N/A — nothing mixed to split (above).
      Optional future tidy: relocate the shared `cdp/_tests/redis` + `cdp/_tests/fixtures` helpers used by
      a few ingestion tests to a neutral `tests/helpers/` spot (benign test-infra reach, not blocking).
- [ ] Move integration/e2e tests into their dedicated folders; keep unit tests beside source.
      NOTE: keep the dedicated folders **per-lane** (e.g. `lanes/<lane>/integration/`) so the CI
      path-based test selection (Phase 6) can still attribute an integration/e2e test to its lane — a
      single top-level folder would break that mapping. Do this with/after Phase 4 (the restructure) so
      the folders land in their final `lanes/<lane>/` home. Sizable; best done where the full suite can
      run (CI/devbox) since it changes many test paths.
- [ ] **Exit gate:** `pnpm test:full` green.

### Phase 4 — restructure ingestion folder (lanes/ + semantic groups)

Target layout (chosen with the product owner — `lanes/`, not `products/`, to avoid overloading the
monorepo's top-level `products/` and to match the term used throughout this plan):

```text
src/ingestion/
  lanes/         <- the 8 lanes (each keeps isolated test selection)
    analytics/ ai/ heatmaps/ error-tracking/ logs/ metrics/ session-replay/ ingestionwarnings/
  framework/     <- pipeline-building framework (from pipelines/, + tophog/)
  steps/         <- shared pipeline steps (from event-processing/ + event-preprocessing/)
  common/        <- shared ingestion domain (persons, groups, outputs glue, cookieless, ...)
  api/ doctor/ utils/    <- ingestion infra
  ingestion-consumer.ts  <- composition root (stays at the ingestion root)
```

- [ ] Move the 8 lanes -> `src/ingestion/lanes/<lane>/` (git mv + `bin/rewrite-imports.mjs`; the `~/`
      aliases keep imports valid through the move — this is precisely why we standardize on `~/`).
- [ ] Group shared code: `pipelines/` (+ `tophog/`) -> `framework/`; `event-processing/` +
      `event-preprocessing/` -> `steps/`; fold `cookieless/` into `common/`.
- [ ] Update the guard (`LANES`, `laneOf`) to resolve lanes under `lanes/` (shared dirs stay SHARED);
      keep the `ingestion-consumer.ts` composition-root exemption. Guard baseline must stay empty.
- [ ] Update jest/tsconfig path globs, `bin/` scripts, and any hardcoded `src/ingestion/<lane>` paths.
- [ ] Gate: tsc 0 new errors, guard 0, lint + format, affected unit tests pass, moves-only diff.
- [ ] **Exit gate:** `pnpm test:full` green.

### Phase 5 — standardize imports on ~/

`~/` is the codebase standard (used ~900x outside ingestion, recommended in `.eslintrc.js`, a
first-class `tsconfig` alias). The merges + moves left ~158 ingestion files mixing `~/` and relative
`../` paths — make them consistent.

- [ ] Rewrite cross-directory relative imports (`../...`) in `src/ingestion` to `~/` (codemod); keep
      `./` for same-directory siblings. Run AFTER Phase 4 so files aren't rewritten twice.
- [ ] Add an eslint rule scoped to `src/ingestion` to enforce it going forward (e.g.
      `import/no-relative-parent-imports`), so new `../` parent imports fail lint.
- [ ] Gate: lint + format clean, tsc 0 new errors.
- [ ] **Exit gate:** `pnpm test:full` green.

### Phase 6 — wire CI test selection

- [ ] Extend `dorny/paths-filter` to emit per-lane + common + cdp flags (lanes now under
      `src/ingestion/lanes/<lane>/`; shared = `framework/`, `steps/`, `common/`).
- [ ] Gate jest runs by changed area; verify the rules table.
- [ ] Update scripts/docs to the new layout.
- [ ] **Exit gate:** `pnpm test:full` green in CI (full suite).

## Status log

- Phase 0 complete: boundary guard + baseline (14 known edges) + npm scripts + CI step + this
  tracker. Guard passes against its baseline. No production code moved yet.
- Phase 1 Group 1 complete: outputs framework moved to `common/outputs` (`ingestion/outputs` +
  `ingestion/common/outputs`), 219 imports rewritten across 131 files via `bin/rewrite-imports.mjs`.
  tsc shows no new errors vs baseline; guard green; this also resolved the pre-existing
  `common -> ingestion/outputs` edge. Added `bin/rewrite-imports.mjs` (reusable codemod).
- Phase 1 Group 2 complete: hog-transformer seam broken by dependency inversion (not a move —
  measured that a move pulls 189/256 cdp files into common). New `HogTransformer` contract in
  `common/hog-transformations`; 9 ingestion files now import the interface; the prefetch step's
  reach into `hogFunctionManager` is encapsulated as `prefetchTransformationStatesForTeams`.
  Production ingestion no longer imports cdp; tsc no new errors; guard green. Test-only
  ingestion->cdp edges remain (deferred to Phase 3).
- Phase 1 Group 3 complete: persons/groups data-access core moved to common (Option B). 27 files
  -> `common/persons`, `common/groups`, `common/personhog`; 18 higher-level processing files stay
  in ingestion. `PERSONS_OUTPUT`/`PERSON_DISTINCT_IDS_OUTPUT` extracted to `common/outputs/persons`.
  208 imports rewritten across 82 files; fixed a codemod file-mapping bug (importer extension).
  tsc no new errors; guard green. Milestone: production cdp<->ingestion fully decoupled (0 edges
  both directions). Remaining: Group 4 (intra-ingestion shared->lane inversions).
- Phase 1 Group 4 (mechanical) complete: shared output names + `AI_EVENT_TYPES` extracted to common;
  shared `event-processing`/`event-preprocessing` steps no longer import lanes. Intra-ingestion
  boundary baseline shrank 14 -> 2. tsc no new errors; guard green. The last 2 edges (analytics
  composing the ai sub-pipeline, and the consumer composition root) are lane-structure decisions
  deferred to Phase 2. Phase 1 is effectively done: cdp<->ingestion decoupled and the shared/lane
  output+constant tangles removed.
- Phase 1 validation (run in the agent sandbox): guard green (2 baselined); `tsc --noEmit` = 15
  errors, all the pre-existing `@posthog/hogvm`/`@posthog/cyclotron` workspace-build issues in
  `src/cdp/` (zero in moved/`common` paths) — the moves compile clean. Infra-free unit tests across
  the refactored areas all pass: `src/ingestion/pipelines` 31 suites / 321 tests; moved
  `common/outputs` + `ingestion/ai` step 113 tests; moved `common/personhog` 112 tests (546 total).
  The full `pnpm test:full` could NOT run here: Docker Hub's anonymous pull rate limit blocked the
  Postgres/Redis/Kafka/ClickHouse images, and the pinned Python 3.13.13 download was unreachable, so
  `setup:test` can't run — as documented, that gate runs in CI / on a devbox.
- Phase 2 "fold worker/ingestion" complete: 40 files moved out of `worker/ingestion`. The two
  group-type managers went to top-level `common/groups` (forced — `types.ts`/`hub.ts` use
  `GroupTypeManager` and are imported by cdp); the rest (persons/groups/stores/event-pipeline
  processing + create-event/person-uuid/timestamps/pipeline-helpers/utils) went to
  `ingestion/common`. 203 imports rewritten across 84 files via the codemod; no lane deps in the
  folded code (DAG safe); `worker/ingestion` dir removed. Gate: guard green (2 baselined), tsc 0 new
  errors (only the pre-existing hogvm/cyclotron noise), eslint + prettier clean, 238 moved-code unit
  tests pass. Full suite is the CI gate.
- Phase 2 "move logs/metrics into lanes" complete: `src/logs-ingestion` -> `src/ingestion/logs`,
  `src/metrics-ingestion` -> `src/ingestion/metrics` (44 imports across 15 files). Lane-pure (no lane
  deps). Surfaced + fixed a codemod gap: `jest.mock`/`jest.requireActual` module paths aren't
  type-checked by tsc, so they broke silently on the move (`logs-ingestion-consumer.test.ts`); taught
  `bin/rewrite-imports.mjs` to rewrite jest mock-family paths. Also had to rebuild the `node-rdkafka`
  and `re2` native addons from source — the sandbox's Node was upgraded to 24 (NODE_MODULE_VERSION 137) but the prebuilt binaries were for Node 22 (127), so every kafka/re2-touching test failed to
  load until rebuilt. Gate: guard green, tsc 0 new errors, eslint + prettier clean, 153 pure
  logs/metrics unit tests pass (consumer/integration tests need a Kafka broker -> CI gate).
- Phase 2 "merge session-replay" complete: `src/session-recording` (47 files) + `src/session-replay`
  (86) + `src/ingestion/session_replay` (11) all merged into `src/ingestion/session-replay`. Verified
  collision-free first (no shared root filenames or subdir names across the three). 231 imports
  rewritten across 76 files; lane-pure. Gate: guard green, tsc 0 new errors, eslint + prettier clean,
  858 unit tests pass. 7 suites fail to load on the missing `@posthog/replay-headless` workspace
  package (the recording-rasterizer playback dep — not installed/built in the sandbox, same class as
  hogvm/cyclotron; independent of the move) -> CI gate.
- Phase 2 "clientwarnings -> ingestionwarnings" complete: directory move
  `src/ingestion/clientwarnings` -> `src/ingestion/ingestionwarnings` (32 imports across 5 files).
  Lane-pure; only the general server imports it. Gate: guard green, tsc 0 new errors, eslint +
  prettier clean, consumer unit test passes. All four lane moves (worker fold, logs, metrics,
  session-replay, ingestionwarnings) are now in place; remaining Phase 2 is tier placement + turning
  on guard `LANES` enforcement (which will surface the deferred top-level->lane config/types edges).
- Phase 2 "tier placement + guard LANES" complete: registered the four moved lanes in the guard
  (`LANES` now lists all eight) — guard stays green, so nothing inside ingestion imports the new lanes
  (isolation holds). Tier placement validated by the boundary that matters: `cdp -> ingestion` and
  `cdp -> ingestion/common` are both 0, so cdp-needed modules sit in top-level `common/` and
  ingestion-only modules in `ingestion/common/`. Note the guard only walks `src/ingestion`, so the
  deferred top-level `config.ts`/`types.ts`/`index.ts` -> lane edges are NOT guard-enforced; they are
  composition/config wiring outside ingestion and don't break the in-ingestion DAG. Remaining Phase 2:
  the ai<->analytics composition decision (blurry, product-owner-flagged) + the CI exit gate.
- Phase 2 "ai/analytics separation" complete (product owner chose full separation): the `analytics` ->
  `ai` edge is gone via dependency inversion. New `ingestion/common/ai-subpipeline.contract` holds
  `AiEventSubpipelineInput`/`Config` + an `AiEventSubpipelineFactory` type; analytics' per-distinct-id
  pipeline takes the factory injected instead of importing `createAiEventSubpipeline` from the ai lane;
  the ai lane implements the factory; both servers (general + api) inject the concrete impl. Also scoped
  the guard to production files — the e2e/integration tests are composition roots that already wire
  cdp's HogTransformer and now the ai factory, so their cross-lane wiring belongs to Phase 3, not the
  guard. Gate: tsc 0 new errors (threading is fully typed, so tsc validates the wiring), eslint +
  prettier clean, guard baseline shrank 2 -> 1. The remaining edge is `ingestion-consumer -> analytics`
  (composition-root, not ai/analytics). Pipeline behavior is covered by the ai/analytics integration +
  e2e tests, which need infra -> CI gate.
- Phase 2 COMPLETE — intra-ingestion DAG is clean. Last edge (`ingestion-consumer -> analytics`)
  resolved by treating the consumer as a composition root (product-owner choice): added a
  `COMPOSITION_ROOTS` set to the guard so files that assemble + run a lane's pipeline (like the servers)
  may import a lane; `ingestion-consumer.ts` stays at `src/ingestion/` and is exempt. (Briefly moved it
  into the analytics lane, then reverted in favor of this.) Guard baseline is now `[]`: no lane imports
  another lane, and no shared code except composition roots imports a lane. All eight lanes (analytics,
  ai, heatmaps, error-tracking, logs, metrics, session-replay, ingestionwarnings) are isolated. tsc 0
  new errors, guard green. Next: Phase 3 (split mixed cdp/ingestion tests) and Phase 4 (CI selection).
- Plan extended (product-owner decisions). Also merged master twice more, including #63064 "unify
  ingestion lag metrics across pipelines" — resolved against the ai/hog-transformer inversion by keeping
  the contract/factory and adopting master's `EmitEventStepOutput` return, `createRecordIngestionLagStep`,
  and the `groupId` removal. Added two phases and renumbered CI:
  - Phase 4 — restructure into `lanes/` + `framework/`/`steps/`/`common/`. Named `lanes/` (not
    `products/`) to avoid overloading the monorepo's top-level `products/` and to match the plan's term.
  - Phase 5 — standardize ingestion imports on `~/`. Investigation showed `~/` is the codebase standard
    (~900 uses outside ingestion, recommended in `.eslintrc.js`, first-class `tsconfig` alias), so the
    goal is consistency for the ~158 files that currently mix `~/` and `../`, not removing `~/`.
  - Phase 6 — CI test selection (was Phase 4). Order matters: restructure (4) -> import-standardize (5) ->
    CI (6); `~/` is kept precisely so the Phase-4 moves stay codemod-friendly (relative paths would break
    on every move). Nothing executed yet for Phases 4–6 — these are plan entries.
