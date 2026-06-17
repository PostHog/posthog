# Ingestion separation refactor

Working tracker for separating ingestion code from the rest of the Node.js service.
This file is the durable source of truth for the refactor loop: each iteration reads the
checklist, does the next unchecked item, runs the gate, commits, checks the item off, and
appends to the status log. Delete this file before the final merge to master.

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
4. Affected unit tests (the touched lane/shared area).
5. Diff is moves-only except for the allowlisted change reasons above.

The full e2e/integration suite needs the Kafka/ClickHouse/Postgres/Redis stack and is a
**CI-only** final gate — not part of the per-iteration loop gate in this sandbox.

Guardrails: work on `claude/affectionate-ritchie-6jh88d`; commit locally per step; do not push
on every iteration.

## Phased checklist (progress tracker)

### Phase 0 — scaffold + guard

- [x] Boundary guard script + baseline (`bin/check-ingestion-boundaries.mjs`).
- [x] `check:boundaries` / `check:boundaries:write` npm scripts.
- [x] Defensive CI step running the guard in the lint job.
- [x] This plan/progress file.

### Phase 1 — break the CDP <-> ingestion seams

- [x] Inventory every CDP->ingestion and ingestion->CDP import.
- [x] Group 1: move the outputs framework (`ingestion/outputs` + `ingestion/common/outputs`)
      -> `common/outputs`; fix imports (219 across 131 files).
- [ ] Group 2: move `cdp/hog-transformations` -> `common/hog-transformations` (breaks the cycle).
- [ ] Group 3: move person/group repositories + `personhog` -> `common/persons`, `common/groups`,
      `common/personhog`.
- [ ] Group 4: invert `event-processing` / `event-preprocessing` shared->lane edges.
- [ ] Baseline shrinks; CDP no longer imports ingestion and vice versa.

### Phase 2 — consolidate into lanes

- [ ] Fold `worker/ingestion` into the ingestion folder.
- [ ] Move `logs-ingestion` -> `logs` lane, `metrics-ingestion` -> `metrics` lane.
- [ ] Merge `session-recording` + `session-replay` + `ingestion/session_replay` -> `session-replay`.
- [ ] Move `clientwarnings` -> `ingestionwarnings` lane dir.
- [ ] Place each shared module in its correct common tier.
- [ ] Add moved lanes to the guard's `LANES` set.

### Phase 3 — split mixed tests

- [ ] Find test files mixing CDP and ingestion logic.
- [ ] Split ingestion logic into its own test (no tests removed).
- [ ] Move integration/e2e tests into their dedicated folders; keep unit tests beside source.

### Phase 4 — wire CI test selection

- [ ] Extend `dorny/paths-filter` to emit per-lane + common + cdp flags.
- [ ] Gate jest runs by changed area; verify the rules table.
- [ ] Update scripts/docs to the new layout.
- [ ] Full suite green in CI.

## Status log

- Phase 0 complete: boundary guard + baseline (14 known edges) + npm scripts + CI step + this
  tracker. Guard passes against its baseline. No production code moved yet.
- Phase 1 Group 1 complete: outputs framework moved to `common/outputs` (`ingestion/outputs` +
  `ingestion/common/outputs`), 219 imports rewritten across 131 files via `bin/rewrite-imports.mjs`.
  tsc shows no new errors vs baseline; guard green; this also resolved the pre-existing
  `common -> ingestion/outputs` edge. Added `bin/rewrite-imports.mjs` (reusable codemod).
