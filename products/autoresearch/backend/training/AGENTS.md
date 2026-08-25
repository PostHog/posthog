# Training loop

Finding a better model for a pipeline's question.
One `run_training()` call → one `AutoresearchTrainingRun` → one sandbox agent session → zero or more `AutoresearchIteration` rows → at most one new champion `AutoresearchModel`.

This is the expensive half of the product. A real run costs roughly a dollar in LLM spend and takes tens of minutes, so almost everything here is built around _not_ wasting a run: the stub path for plumbing tests, the safety net for agents that die mid-flight, and server-side champion selection so a confused agent cannot promote itself.

The other half is `../inference/`, which consumes what this package produces and must never re-fit.

This package landed ahead of one caller. `../temporal/` arrives in a later piece of the split tracked in [#88464](https://github.com/PostHog/posthog/pull/88464), so the references to it below describe where it will sit.

## What lives here

- `runner.py`
  The real path. `run_training()` creates the `AutoresearchTrainingRun` (status `RUNNING`) and fires `Task.create_and_run()` with `internal=True` and no repository, so the run shows up as an internal Task rather than in the normal Tasks list.
  `build_agent_description()` assembles the agent's brief — the target, the horizon, the population, and the contract for the bundle it must author.
  The agent drives the rest _itself_ through the `autoresearch-*` MCP tools: it records each iteration, uploads the bundle, and calls complete. Nothing polls it.
- `stub.py`
  `run_stub_training()` — a hand-authored champion recipe with universal engagement features (event counts, distinct event types, days since first seen) that apply to any team and any target.
  No agent, no LLM spend, deterministic. This is what `--stub` on `autoresearch_train` uses, and it is the right tool for testing anything downstream of training.
- `ingestion.py`
  The safety net. `handle_task_run_completed()` is called from the `TaskRun` `post_save` signal registered in `../apps.py`, and runs synchronously in the Temporal worker thread.
  If the agent recorded iterations but never called complete, this finalizes through the same promotion path. If it recorded nothing, the run is marked failed — which is what produces `"Agent recorded no iterations before the run ended."`
- `promotion.py`
  Champion selection. `complete_training_run()` is the single entry point, used both by the training-run `complete` API action and by `ingestion.py`.
  A challenger must beat the incumbent by `CHAMPION_PROMOTION_MARGIN` (0.005 holdout AUC) to be promoted — near-ties keep the incumbent rather than churning the champion on noise.
  `_detect_uploaded_bundle()` decides whether the new model gets an `artifact_prefix` (bundle path) or only a recorded recipe (legacy path).
- `artifacts.py`
  Object storage for the bundle: `features.sql`, `train.py`, `predict.py`, plus the fitted `model.pkl` written at completion.
  Keys are prefixed by team / pipeline / training-run (`bundle_prefix()`), so history is preserved naturally and bundles can never collide across tenants.
  `normalize_artifact_path()` and `MAX_ARTIFACT_BYTES` (10 MiB) are the guardrails on agent-supplied paths — the agent chooses these strings, so treat them as untrusted input.
- `recipe_validation.py`
  Server-side validation of whatever an agent records. `validate_feature_sql()` parses the SQL and enforces the one-row-per-person contract: a read-only `SELECT` keyed as `person_id AS distinct_id` (the exact column the training join and materialization read), with the `{anchors}` placeholder required so every feature query is cut off at each person's T0, and no wall-clock functions (`now()`, `today()`, ...) because a window bound to "now" reads outcome-window events at training time (target leakage). It does not prove every event read is bounded by `cutoff_ts`; that remains the agent's contract. `validate_unique_distinct_ids()` re-checks the one-row-per-person contract on actual materialized rows, where duplicates first become visible.
  `validate_model_class()` is deliberately **not** applied at recording time — in the bundle world the agent's real model is arbitrary sandboxed code, so a recorded `model_class` is informational. The allowlist is enforced only where it is a genuine code-execution surface: the legacy in-process path in `../inference/scoring.py`, which resolves it through `importlib`.

## Mental model

The agent proposes, the backend disposes.

1. `run_training()` inserts the run row and launches the sandbox. The run's id is handed to the agent so it can address its own run over MCP.
2. The agent explores with HogQL, tries a feature set plus a model spec, evaluates on holdout, and records the result as an `AutoresearchIteration` with `status` `kept` or `discarded` and its own `agent_confidence`.
   Recording is live — rows appear during the run, not in a batch at the end.
3. When it is satisfied it uploads the bundle and calls complete.
4. `complete_training_run()` reads the iterations, picks the best by holdout score, applies the promotion margin, and writes the `AutoresearchModel`.

The agent's `status` on an iteration and its confidence are _evidence_, not a decision. `_select_best_iteration()` is what actually chooses.

Two things routinely surprise people:

- **`AutoresearchTrainingRun.iteration_count` is only written at completion.** Iteration rows land live, so a run in flight reads `0/5` with rows already in the table. Poll the rows, not the counter.
- **`autoresearch_train` does not enforce `../dataset/validation.py`.** A target that fails validation on volume will still train. That is deliberate for local dev on thin datasets, but it means a run can "succeed" on far too few rows.

## Where the rest of the system meets this package

- **Launched by** — the `train` API action in `../presentation/views/views.py`, the `autoresearch_train` management command, and `activity_kickoff_training` in `../temporal/workflows.py`.
- **Finalized by** — the `complete` action on the training-run viewset, or `ingestion.py` via the `TaskRun` `post_save` signal wired in `../apps.py`.
- **Consumed by** — `../inference/`, which reads the champion's `artifact_prefix` and runs its bundle. `fit_champion_model()` in `../inference/sandbox.py` is what actually fits and persists `model.pkl` at completion time.
- **Agent-facing surface** — the `autoresearch-training-runs-*` MCP tools in `../../mcp/tools.yaml`, backed by the viewsets in `../presentation/views/views.py`. The sandbox agent has no other way to write.
- **Labels and features** — `../dataset/labeling.py` builds the training population the bundle is fitted against.

## When editing this flow

- **Never let agent output select the champion.** Everything that decides goes through `complete_training_run()`. If you add a new completion path, route it there rather than writing an `AutoresearchModel` directly.
- **Any new agent-writable field needs validation in `recipe_validation.py`.** The agent is an untrusted author: SQL it writes is executed, paths it supplies become storage keys.
- **Keep `stub.py` working.** It is the only way to test the whole downstream chain without spending money, and it is what local E2E leans on. If you change the recipe shape, change the stub too or every plumbing test silently starts covering nothing.
- **Both model shapes must keep working.** A model with an `artifact_prefix` runs its bundle; one without carries only `model_recipe` and takes the legacy in-process path. Do not assume `artifact_prefix` is populated.
- If you change the bundle file set or layout, update `artifacts.py`, the agent brief in `runner.py`, and `../../backend/test_fixtures/bundle/` together — the fixtures are what the tests fit against.
- **If you change this package's layout or the agent contract, update this file to match.**
