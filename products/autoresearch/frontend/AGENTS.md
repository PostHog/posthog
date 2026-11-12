# Frontend

Three scenes behind the `autoresearch` feature flag: the pipeline list, the create form, and a single pipeline's detail view.

The product is mostly a backend, and the UI is deliberately thin — it reads status and results rather than doing any modeling work. What it mainly has to get right is honestly representing a long-running, partly-asynchronous process whose rows arrive at different times.

## What lives here

| File                            | Scene / role                                                                                                                                |
| ------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| `AutoresearchScene.tsx`         | `/autoresearch` — the model list: search and sort, a container-query grid of model cards, and the "New model" entry point.                  |
| `modelList.ts`                  | The model list's search (name, target event and its display name) and sort (recently created, needs attention, name).                       |
| `AutoresearchModelCard.tsx`     | One model card: the question, a headline metric per state (draft, training, awaiting check, confirmed). `ModelCardMenu.tsx` holds actions.  |
| `pipelineQuestion.ts`           | The card and header title (a name written as a question, else "Who will do “X” in the next N days?"), `eventName()` and the subtitle.       |
| `AutoresearchNewScene.tsx`      | `/autoresearch/new` — the create form. Its parts live in `newModel/`.                                                                       |
| `AutoresearchPipelineScene.tsx` | `/autoresearch/:id` — the detail shell: the question header, the lifecycle strip, and four tabs. Each tab lives in `pipeline/`.             |
| `autoresearchLogic.ts`          | List logic — loads pipelines, lifecycle actions, and setup-status detection for the empty-state gate.                                       |
| `autoresearchNewLogic.ts`       | Create form: a `kea-forms` form that validates the definition, then creates the model and optionally starts training.                       |
| `newModel/`                     | Create-form parts: template chips, definition sentence, population picker, Advanced section, readiness checklist, "What happens next".      |
| `firstRunCheck.ts`              | The check before a draft's first run, shared by the list card and the model page: validate, then confirm a run the check did not pass.      |
| `autoresearchPipelineLogic.ts`  | Detail logic. Also maps the old `?tab=` keys to the four tabs, so saved links still open.                                                   |
| `pipelineLifecycle.ts`          | The five lifecycle steps (question set to checked against reality) and which one is current.                                                |
| `trainingScheduleLogic.ts`      | Setup tab training settings and their save, the project's limits and usage, the status line, and why the limits disable Train now.          |
| `agentSearch.ts`                | The agent's search across training runs: chart points, best score so far, change per experiment within a run, log groups and status brief.  |
| `onlinePerformance.ts`          | Accuracy tab helpers over the `online_performance` endpoint: the stat tiles, the per-metric accuracy trend, predicted against actual.       |
| `predictionCoverage.ts`         | Predictions tab coverage from the runs list: the measured summary and the coverage and score age per day.                                   |
| `predictionSegments.ts`         | The likelihood segments from the cut points the `online_performance` endpoint returns: lift over the base rate, or a fixed pair until then. |
| `PipelineStatusTag.tsx`         | Status tag + tooltip shared by the list and detail scenes.                                                                                  |
| `ProbabilityHistogram.tsx`      | Decile histogram of the latest scoring run's probabilities.                                                                                 |
| `DailyVolumeChart.tsx`          | Bar-per-day chart of scoring volume.                                                                                                        |
| `pipeline/`                     | The detail-scene tabs and their components. Agent research stacks a status brief, a steer bar, the search chart and the run log.            |
| `emptyState/`                   | `ProductEmptyState` config + example-data preview for the first-run gate.                                                                   |
| `generated/`                    | **Generated. Never hand-edit.** Change the serializer in `../backend/presentation/views/serializers.py` and run `hogli build:openapi`.      |

Scene registration, routes, and urls live in `../manifest.tsx`.
`frontend/src/products.tsx` is generated from the manifests — hand-editing it there gets wiped by `pnpm build:products`. Only the `Scene` enum entries belong in `sceneTypes.ts`.

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
- Usage events are part of the API: renaming one breaks every insight built on it. The list logic captures `autoresearch model list viewed`, `autoresearch model list load failed`, `autoresearch model list searched` (with `result_count`, debounced), `autoresearch model list sorted` (with `sort`), `autoresearch model deleted` / `paused` / `resumed`, `autoresearch model training started` (with `source: 'list'` from a card), `autoresearch model card clicked`, and `autoresearch model action failed` (with `action`). The create logic captures `autoresearch model template selected` (with `template_key`), `autoresearch model custom chosen`, `autoresearch model advanced opened`, `autoresearch model validated` (with `can_proceed`, `error_code`, `population_choice` and `population_has_event`), `autoresearch model created` (with `action`: `start_training` or `save_draft`, `population_choice` and `validation_error_code`), and `autoresearch model training started` / `training start failed`. The list and detail logics capture `autoresearch model training check failed` (with `source`: `list` or `model`, and `error_code`) when the check before a draft's first run fails, and `autoresearch model training check overridden` when the person starts the run anyway. The detail logic captures `autoresearch model tab changed` (with `tab`) when a person picks a tab, `autoresearch model experiment log filter changed` (with `filter`), `autoresearch model accuracy cutoff changed` (with `cutoff`, and `source`: `flagged` or `trend` for the card that changed it), `autoresearch model accuracy trend metric changed` (with `metric`), `autoresearch model accuracy trend challengers toggled` (with `shown`), `autoresearch model lowest bucket toggled` (with `hidden`) when a person shows or hides the 0-10% bucket of the Predictions tab histogram, `autoresearch model search point clicked` (with `run_id`, `iteration_number`, `status`), `autoresearch model experiment details opened` (with `run_id`, `iteration_number`) when a person opens an experiment's working notes, `autoresearch model suggestion sent` (with `priority`), `autoresearch model training stopped` (with `run_id`) when a person confirms Stop training, `autoresearch agent research experiment opened` (with `run_id`, `iteration_number`, `status`, `source`: `chart` or `log`) when a person opens the experiment drawer, `autoresearch agent research steer opened` (with `queued_count`) `autoresearch agent research full notes opened` (with `run_number`) `autoresearch training schedule changed` (with `research_interval_days` and `iterations_per_run`), and `autoresearch research model changed` (with `agent_model` and `agent_reasoning_effort`, null meaning the default) when a save changes either; buttons carry a `data-attr` for autocapture. Extend the same names when you add a scene.

## Copy

Sentence case, not Title Case. Invoke `/writing-user-facing-copy` before adding or changing any visible string.

The settled user-facing word for the entity is **"model"** ("New model", "Delete model", "Model paused").
"Pipeline" is the internal name — it stays in code symbols and the backend, and must not appear in copy.

## The population in the create form

A custom model has no population until the person chooses one: people who did an event, or all identified users.
Until then the form does not validate, Start training is disabled, and Save as draft shows an error.
"All identified users" stores no population kind, so the check reads every event in the training lookback and can run out of time on a high-volume project.
The validate response's `error_code` decides the readiness panel: `too_expensive` points at the population picker and offers no Retry, `invalid_definition` offers no Retry either, and `unavailable` offers Retry.
A draft saved without a passing check runs the same check before its first run (`firstRunCheck.ts`).

## Templates in the create form

A template chip calls resolve-template and writes the result into the same `newPipeline` form that a custom definition uses.
The template's semantic population spec (`{"kind": ...}`) sits in `inference_population_kind` and `training_population_kind`, and the request merges it with the property filters.
A change to the target or the horizon re-resolves the template. The name and the training lookback follow the template only until the user edits them.
Templates take event targets only, so the target picker hides actions while a template is selected.

## When editing this flow

- Regenerate types after any serializer change and commit the result; CI checks for drift.
- Register new scenes in `../manifest.tsx`, not in the generated `products.tsx`.
- **If you add a scene or change the routes, update this file to match.**
