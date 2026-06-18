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
- Each ingestion lane has its own directory inside the ingestion folder.
- All pipeline-framework code lives in a `pipelines` folder.
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

Wired in Phase 4, after the DAG holds.

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
- [ ] **Exit gate:** `pnpm test:full` green (verify in CI on push — full suite not runnable in the
      agent sandbox).

### Phase 2 — consolidate into lanes

- [ ] Fold `worker/ingestion` into the ingestion folder.
- [ ] Move `logs-ingestion` -> `logs` lane, `metrics-ingestion` -> `metrics` lane.
- [ ] Merge `session-recording` + `session-replay` + `ingestion/session_replay` -> `session-replay`.
- [ ] Move `clientwarnings` -> `ingestionwarnings` lane dir.
- [ ] Place each shared module in its correct common tier.
- [ ] Add moved lanes to the guard's `LANES` set.
- [ ] Resolve the 2 deferred intra-ingestion edges (`analytics` -> `ai` via `createAiEventSubpipeline`,
      and `ingestion-consumer` -> `analytics`). Intent (per product owner): AI and analytics are
      separate lanes in the long run, but the split is still mid-migration so the boundary is blurry
      today — lean toward separation (e.g. wire the AI sub-pipeline at the composition root rather
      than the analytics lane importing it) without forcing a premature clean break.
- [ ] **Exit gate:** `pnpm test:full` green.

### Phase 3 — split mixed tests

- [ ] Find test files mixing CDP and ingestion logic.
- [ ] Split ingestion logic into its own test (no tests removed).
- [ ] Move integration/e2e tests into their dedicated folders; keep unit tests beside source.
- [ ] **Exit gate:** `pnpm test:full` green.

### Phase 4 — wire CI test selection

- [ ] Extend `dorny/paths-filter` to emit per-lane + common + cdp flags.
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
