# Autoresearch

Agent-driven predictive modeling.
A user names a **target event**, a **population**, and a **horizon** ("who will download a file in the next 30 days?").
An agent then searches for the best model for that question, and once it finds one, the product scores the population on a cadence and writes the result back into PostHog as `autoresearch_prediction` events.

The framing is Karpathy's `autoresearch` prompt pattern: an agent edits one thing, runs a fixed eval, keeps the change if a single metric improved, reverts otherwise, and loops until a stop rule fires.
Here the "one thing" is a feature set plus a model spec, the fixed eval is holdout AUC on a labeled training population, and the loop runs inside a Tasks sandbox.

## The two loops

Everything in this product is one of two loops. Keep them straight — they have different cadences, different failure modes, and different data contracts.

- **Training loop** (`backend/training/`) — runs rarely, costs real money.
  Launches an agent in a sandbox, which explores the team's events with HogQL, records each experiment as an `AutoresearchIteration`, and authors a runnable **bundle** (`features.sql` / `train.py` / `predict.py`).
  The backend — never the agent — then picks the champion.
- **Inference loop** (`backend/inference/`) — runs on a cadence, must be cheap and boring.
  Loads the champion, materializes the inference population, runs the bundle's `predict.py`, and emits one `autoresearch_prediction` event per scored person.

`backend/evaluation/` closes the circle after the fact: once a prediction's horizon has elapsed, it joins the emitted events back to what actually happened and computes realized AUC, Brier, calibration error, and lift@k.

## Where things live

| Path                  | What it owns                                                                                                                              |
| --------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `backend/api/`        | DRF viewsets + serializers — the HTTP surface, and via drf-spectacular the source of both the generated frontend types and the MCP tools. |
| `backend/dataset/`    | What the prediction problem _is_: population resolution, `(person, T0, label)` triples, target viability checks, built-in templates.      |
| `backend/training/`   | The training loop: sandbox agent launch, iteration recording, champion promotion, artifact-bundle storage.                                |
| `backend/inference/`  | Scoring: bundle-in-sandbox (current) and in-process recipe (legacy), plus event emission.                                                 |
| `backend/evaluation/` | Online validation once predictions mature.                                                                                                |
| `backend/temporal/`   | Scheduled workflows on `autoresearch-task-queue` — coordinator, inference, validation.                                                    |
| `backend/management/` | Headless entrypoints for local dev and E2E: train, score, validate, validate-online.                                                      |
| `backend/models.py`   | All six Django models. Read this before anything else.                                                                                    |
| `frontend/`           | The scenes behind the `autoresearch` flag.                                                                                                |
| `mcp/tools.yaml`      | The `autoresearch-*` MCP tool surface the sandbox agent drives itself with.                                                               |

Each backend package has its own `AGENTS.md`. Read the one for the package you're editing.

## Data model in one pass

```text
AutoresearchPipeline          the standing question (target, population, horizon, cadence)
 ├─ AutoresearchTrainingRun   one attempt to find a better model
 │   └─ AutoresearchIteration one experiment inside that attempt (kept / discarded)
 ├─ AutoresearchModel         a trained model — role = champion | challenger | archived
 ├─ AutoresearchRun           one execution of inference or validation
 └─ AutoresearchSuggestion    a human- or agent-authored hypothesis for the next run to explore
```

`AutoresearchModel.artifact_prefix` points at the bundle in object storage.
When it's empty the model predates bundles and carries only `model_recipe` — the legacy in-process path.
Both still exist; see `backend/inference/AGENTS.md`.

## Invariants that cross package boundaries

These are the ones that have actually broken things. Each package's `AGENTS.md` covers its own rules.

- **Everything is keyed on `person_id`, one row per person.**
  Agent-authored `feature_sql` must be a read-only `SELECT` keyed on `person_id`, and the label and population queries key on it too.
  A mismatch here does not raise — it silently produces all-zero labels and a degenerate model.
  **A uniform score distribution is an identifier mismatch until proven otherwise, not a bad model.**
- **`backend/dataset/labeling.py` is the single source of truth for what a training example is.**
  Three call sites depend on it (the wizard's estimate, the trainer, inference-time cutoff). They share the module so they cannot drift apart.
- **The agent proposes; the backend disposes.**
  Iterations are recorded by the agent but champion selection happens server-side in `backend/training/promotion.py`.
  Never let agent output pick the champion directly.
- **Autoresearch trains on identified users only.**
  On demo-style datasets that are largely anonymous, raw event counts wildly overstate how much training data exists.

## Feature flag and access

Gated by the `autoresearch` feature flag (`backend/access.py`); rollout is configured on the flag, and code only asks whether it is on.
Management commands bypass the gate entirely, which is why local E2E works without any flag setup for the CLI path but not for the API or UI.

The real-agent training path additionally needs Tasks access, since it runs in a Tasks sandbox.

## Known gaps

- **`iteration_count` on a training run is only written at completion**, while `AutoresearchIteration` rows land live during the run. The UI derives in-flight progress from the live iteration rows (`trainingRunProgress` in `frontend/autoresearchPipelineLogic.ts`), so only API consumers reading the persisted counter see `0` mid-run.
- Older notes claim the UI has no create flow and that the "New prediction" button is disabled. That is out of date — `/autoresearch/new` is wired up and creates pipelines through the generated API. See `frontend/AGENTS.md`.
