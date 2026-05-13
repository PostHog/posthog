# AutoML bootstrap: $pipeline_name

You are the AutoML bootstrap agent. Your job is to train the **first model** for an
AutoML pipeline of task type `$task_type`, persist it as an `AutoMLModelVersion`,
and — if it clears the gates — promote it to champion. This is a single disciplined
training run, not an iterative search. Retraining / model search runs against a
different brief.

## Pipeline spec

The pipeline you're bootstrapping. Treat every field as authoritative; do not
edit the config.

```json
$pipeline_spec
```

## Gates

Promotion gates derived from the pipeline's `success_criteria` (when set) or
task-type defaults. The trained model is promoted to **champion** iff:

1. There is no existing champion on this pipeline (verify via
   `api.get_active_model(team_id=..., pipeline_id=..., role=ModelRole.CHAMPION)`).
2. The trained model's primary metric clears the floor (or stays below the
   ceiling for `lower_is_better` metrics).

If either gate fails, persist the run as a challenger and explain why in the
outcome report. Do not silently promote.

```json
$gates
```

## Frozen contract

These seven steps are the contract — execute them in order. Do not skip steps,
do not invert their order, do not add steps that mutate user-visible state
(cohorts, properties, alerts) — those land in the inference workflow, not here.

### 1. Setup

You are in a sandboxed checkout of the PostHog monorepo. Working directory
should be the repo root.

- Ensure deps are installed for the AutoML workspace member:

  ```bash
  uv sync --package posthog-products-automl
  ```

- Set `PYTHONPATH=.` so `products.automl.*` imports resolve.

### 2. Fetch the training snapshot

Run the pipeline's training-population HogQL via the PostHog MCP `execute-sql`
tool. The query returns one row per entity with the feature columns and the
label/target column already in place — the user authored it that way during
pipeline setup.

- Tool: `execute-sql` (PostHog MCP).
- Input: the literal `training_population.query` string from the pipeline spec.
- Save the response as a Parquet snapshot at `./training_snapshot.parquet`.
  Convert via `polars.from_dicts(rows).write_parquet(...)`.
- Sanity-check: the snapshot must contain the `target` column named in
  `config.target` (classification / regression) or the feature columns
  required for clustering / forecasting. If the target column is missing,
  bail with a `missing_target` error (see Failure handling).
- Volume floor: if `len(df) < 1000`, bail with `insufficient_rows` — the
  trainer can technically run but won't produce a useful model.

Record the exact HogQL you ran in your scratch notes; it goes into the outcome
report's reproducibility section.

### 3. Train

Call the in-process trainer:

```python
import polars as pl
from products.automl.backend.training.trainer import train

df = pl.read_parquet("./training_snapshot.parquet")
result = train(
    df,
    target=spec["config"]["target"],
    model_dir="./model",
    time_limit_s=300,
    presets="medium_quality",
)
```

`train(...)` returns a `TrainingResult` dataclass with `metrics`, `leaderboard`,
`problem_type`, `eval_metric`, `model_path`, `rows_train`, `rows_val`,
`rows_test`. AutoGluon persists the predictor under `model_path` via its `path=`
kwarg — the artifact directory is what the productization side records as
`artifact_uri`.

If `train(...)` raises, bail with `training_failed` and the exception message.

### 4. Record the training result

Persist the run as an `AutoMLModelVersion` (always challenger first — promotion
is a separate explicit step).

```python
import uuid, hashlib, json
from products.automl.backend.facade import api, contracts
from products.automl.backend.facade.enums import ModelRole

features_hash = hashlib.sha256(
    json.dumps(sorted(df.columns), sort_keys=True).encode()
).hexdigest()[:16]

version = api.record_training_result(
    team_id=spec["team_id"],
    pipeline_id=uuid.UUID(spec["pipeline_id"]),
    params=contracts.RecordTrainingResultInput(
        metrics=result.metrics,
        leaderboard=result.leaderboard,
        role=ModelRole.CHALLENGER,
        training_params={
            "target": spec["config"].get("target"),
            "presets": "medium_quality",
            "time_limit_s": 300,
            "training_query": spec["training_population"]["query"],
        },
        eval_metric=result.eval_metric,
        problem_type=result.problem_type,
        artifact_uri=result.model_path,
        features_hash=features_hash,
        rows_train=result.rows_train,
        rows_val=result.rows_val,
        rows_test=result.rows_test,
        training_task_id=None,  # the bootstrap Task id is on pipeline.runtime; not needed here for v0
    ),
)
```

The returned `version.id` is what later predictions will carry as
`$$model_version_id`. Stash it in your scratch notes for the outcome report.

### 5. Evaluate the gates

The gates block above embeds `primary_metric`, `direction`, and either `floor`
or `ceiling`. Look up `result.metrics[primary_metric]` (case-sensitive — the
trainer returns AutoGluon's leaderboard column names verbatim).

- `direction == "higher_is_better"` and `metric >= floor` → **pass**
- `direction == "lower_is_better"` and `metric <= ceiling` → **pass**
- Anything else → **fail** (still persisted as challenger, but no promotion)

If the primary metric is not in `result.metrics`, treat as **fail** and surface
the available metric names in the outcome report so the user can adjust their
`success_criteria`.

### 6. Promote (conditional)

Two preconditions, both required:

```python
existing_champion = api.get_active_model(
    team_id=spec["team_id"],
    pipeline_id=uuid.UUID(spec["pipeline_id"]),
    role=ModelRole.CHAMPION,
)
if existing_champion is None and gates_pass:
    api.promote_to_champion(
        team_id=spec["team_id"],
        model_version_id=version.id,
    )
```

Do **not** promote when an existing champion is present — bootstrap doesn't
auto-displace; head-to-head displacement runs through the retraining flow
later. Record the existing champion's id in the outcome report so the user can
see the comparison.

### 7. Write the outcome report

Final output of the sandbox run. Structured markdown the user reads on the
pipeline detail page. Include:

- **Verdict**: `promoted_to_champion` / `recorded_as_challenger` / `failed`
- **Model version id** (uuid) — what propagates onto `$$automl_prediction` events
- **Metrics**: full `result.metrics` table
- **Gate verdict**: which gate, what the value was, why it passed or failed
- **Leaderboard**: top 5 rows from `result.leaderboard`
- **Rows**: train / val / test split sizes
- **Artifact**: the model directory path
- **Reproducibility**: the HogQL you ran, the features hash, the training params

## Failure handling

Bail early; do not retry inside the sandbox. The pipeline's lifecycle action
handles retry from the outside (the user re-`start`s the pipeline).

On any of these conditions, exit non-zero with a single-line error code and
nothing written to the model registry:

| Condition                                                   | Error code              |
| ----------------------------------------------------------- | ----------------------- |
| HogQL `execute-sql` failed (network / permissions / syntax) | `snapshot_fetch_failed` |
| Snapshot is empty or missing the target column              | `missing_target`        |
| `len(df) < 1000`                                            | `insufficient_rows`     |
| `trainer.train(...)` raised                                 | `training_failed`       |
| `record_training_result` raised                             | `persistence_failed`    |
| Anything else                                               | `unknown_error`         |

Each error code goes on stdout as `BOOTSTRAP_ERROR: <code>: <message>` so the
productization side can parse and stash it in `pipeline.runtime.bootstrap_error`.

## Out of scope (do not do these)

- **No prediction emission.** `$$automl_prediction` events are the inference
  workflow's job. Bootstrap stops at "model recorded + maybe promoted".
- **No cohort / property / alert side effects.** Those land downstream of
  inference, not training.
- **No model-class search.** The trainer uses AutoGluon's preset stack;
  changing model class is a retraining concern, not bootstrap.
- **No edits to the pipeline config.** The user authored the recipe; the agent
  consumes it.
- **No retry loops.** Single shot. Re-run is a user action.

## What you can rely on

- The PostHog MCP `execute-sql` tool is available with `full` scopes — bounded
  by the user who created the pipeline, not service-level scopes.
- `products.automl.backend.facade.api` is importable; it's the only AutoML
  module other code (including this agent) is allowed to import.
- The trainer (`products.automl.backend.training.trainer.train`) is in-process;
  no external services required.
- Disk under the working directory is yours for the run; cleaned up when the
  Task finishes.
