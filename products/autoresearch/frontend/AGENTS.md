# Frontend

Three scenes behind the `autoresearch` feature flag: the pipeline list, the create form, and a single pipeline's detail view.

The product is mostly a backend, and the UI is deliberately thin — it reads status and results rather than doing any modeling work. What it mainly has to get right is honestly representing a long-running, partly-asynchronous process whose rows arrive at different times.

## What lives here

| File                            | Scene / role                                                                                                                           |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `AutoresearchScene.tsx`         | `/autoresearch` — the pipeline list, with row actions (archive, pause, resume, delete) and the "New model" entry point.                |
| `AutoresearchNewScene.tsx`      | `/autoresearch/new` — the create form.                                                                                                 |
| `AutoresearchPipelineScene.tsx` | `/autoresearch/:id` — the detail shell: title bar actions and the tab strip. Each tab lives in `pipeline/`.                            |
| `autoresearchLogic.ts`          | List logic — loads pipelines, lifecycle actions, and setup-status detection for the empty-state gate.                                  |
| `autoresearchNewLogic.ts`       | Create form — a `kea-forms` form that validates the target, then calls the generated `autoresearchCreate`.                             |
| `autoresearchPipelineLogic.ts`  | Detail logic.                                                                                                                          |
| `PipelineStatusTag.tsx`         | Status tag + tooltip shared by the list and detail scenes.                                                                             |
| `ProbabilityHistogram.tsx`      | Decile histogram of the latest scoring run's probabilities.                                                                            |
| `DailyVolumeChart.tsx`          | Bar-per-day chart of scoring volume.                                                                                                   |
| `pipeline/`                     | One file per detail-scene tab (Overview, Training, Predictions, Online performance, Suggestions) and their components.                 |
| `emptyState/`                   | `ProductEmptyState` config + example-data preview for the first-run gate.                                                              |
| `generated/`                    | **Generated. Never hand-edit.** Change the serializer in `../backend/presentation/views/serializers.py` and run `hogli build:openapi`. |

Scene registration, routes, and urls live in `../manifest.tsx`.
`frontend/src/products.tsx` is generated from the manifests — hand-editing it there gets wiped by `pnpm build:products`. Only the `Scene` enum entries belong in `sceneTypes.ts`.

## The create flow exists

`/autoresearch/new` is live. `autoresearchNewLogic.ts` builds the target request (event name or action id), validates it against the pipeline `validate` endpoint, and creates via the generated `autoresearchCreate` client.

Older internal notes say the button is disabled and pipelines can only be made via the management command or API. That has not been true since this scene landed. If you are reading a doc that says otherwise, the doc is stale.

## Representing an in-flight run honestly

This is where the UI is easiest to get wrong, because the backend writes a training run's state in two stages:

- `AutoresearchIteration` rows land **live**, during the run.
- `AutoresearchTrainingRun.iteration_count`, `best_holdout_score`, and the champion `AutoresearchModel` land **only at completion**.

So a healthy run in progress reads `0/5` iterations with five iteration rows already in the database and no model at all. Rendering the counter alone makes a working run look stalled. Prefer the iteration rows for progress, and treat a missing champion on a `running` pipeline as normal rather than as an empty state.

Pipeline status has six values (`draft`, `bootstrapping`, `running`, `converged`, `paused`, `archived`) and a fresh pipeline sits in `bootstrapping` for the whole first training run.

## Conventions

Follow `frontend/src/AGENTS.md` — it applies to product frontends too.

- **Business logic goes in the kea logic, not the component.** Avoid React hooks.
- **Import generated API types**; never hand-write an interface that duplicates a serializer.
- TypeScript with explicit return types; Tailwind utilities rather than inline styles.
- Reuse Lemon / quill components instead of hand-rolling tables, badges, or tags.
- Any button that fires a request must guard against double-submission — `loading` / `disabledReason` on `LemonButton`, reset on both success and error paths. The lifecycle actions here (train, score, archive, pause, resume) are all network calls, and several are expensive: firing `train` twice starts two sandbox agent runs and spends the budget twice.

## Copy

Sentence case, not Title Case. Invoke `/writing-user-facing-copy` before adding or changing any visible string.

The settled user-facing word for the entity is **"model"** ("New model", "Delete model", "Model paused").
"Pipeline" is the internal name — it stays in code symbols and the backend, and must not appear in copy.

## When editing this flow

- Regenerate types after any serializer change and commit the result; CI checks for drift.
- Register new scenes in `../manifest.tsx`, not in the generated `products.tsx`.
- **If you add a scene or change the routes, update this file to match.**
