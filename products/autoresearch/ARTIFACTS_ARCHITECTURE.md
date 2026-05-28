# Autoresearch: artifact-based architecture

Status: design draft. Not yet implemented. Supersedes the current JSON-recipe-in-Postgres
approach once we've agreed on the open questions at the bottom of this doc.

## TL;DR

Each training run produces a **runnable Python project** stored in object storage:
agent-authored `train.py`, `predict.py`, `features.sql`, `recipe.yml`, `README.md`,
plus one Jupyter notebook per iteration. The framework executes those scripts in
a controlled sandbox image both at training-time (to verify) and at inference-time
(re-fit every run — this is intentional regularization). The same MCP upload
surface that the sandbox agent uses is also what a data scientist hits from their
laptop, so human-driven iterations and agent-driven iterations are first-class
peers.

## Principles

1. **Recipe is source of truth.** The artifacts (Python files + SQL) fully describe
   the model. There is no separate "fitted model" of record — the fit is a deterministic
   function of the recipe and the data at scoring time.
2. **Refit every inference run is a feature.** When training data drifts or the recipe
   starts misbehaving, performance changes are visible immediately. We get drift
   detection as a side effect.
3. **Agent has freedom inside a controlled environment.** The sandbox image pins the
   library surface (sklearn, pandas, numpy, joblib at known versions). Inside that,
   the agent decides everything — feature engineering, preprocessing pipelines, model
   choice, hyperparameter ranges, custom transformers.
4. **Sandbox-agent and laptop-user are the same caller.** Both go through the MCP
   `autoresearch-artifacts-*` tools. There is no privileged "agent path" the framework
   trusts more than a human submission.
5. **Iterations are the work log.** Each iteration writes a Jupyter notebook describing
   what it tried, what worked, what didn't. Next training run starts by reading the
   prior winner's notebook + prior champion's `train.py` — never starts from a blank
   page.
6. **Reproducible off-platform.** Any user can download the artifact bundle, run
   `python train.py` on their laptop with PostHog-fetched data, and reproduce the model
   bit-for-bit (modulo `random_state`).

## Artifact layout

Each training run owns one directory in object storage:

````text
{team_id}/autoresearch/{pipeline_id}/{training_run_id}/
├── recipe.yml             # declarative metadata (see §recipe.yml)
├── features.sql           # HogQL with {anchors} placeholder
├── train.py               # standalone — fits sklearn Pipeline, prints holdout_auc
├── predict.py             # standalone — applies fitted Pipeline to inference features
├── README.md              # agent's plain-English narrative + iteration summary
├── requirements.txt       # pinned (subset of the sandbox image's locked versions)
└── eda/
    ├── iter-1-data-shape.ipynb
    ├── iter-2-recency-features.ipynb
    ├── iter-3-gbm-tuning.ipynb
    └── iter-N-winner.ipynb
```text

Stored via PostHog's existing `posthog.storage.object_storage` abstraction (MinIO
in dev, S3 in prod). Path keyed by `training_run_id` so history is preserved
naturally. Champion / challenger / archived state lives on the `AutoresearchModel`
row in Postgres, not in the storage layout.

## File contracts

### `features.sql`

The agent's HogQL feature query. Same `{anchors}` contract as today (see Step B
of the existing build) — must reference `cutoff_ts`, must not call `now()`.

The framework substitutes `{anchors}` at execution time:

* **Training**: `(SELECT person_id, t0_ts AS cutoff_ts FROM labeled_anchors)`
* **Inference**: `(SELECT DISTINCT person_id, toInt(toUnixTimestamp(now())) AS cutoff_ts FROM events WHERE ...)`

Output is `features.parquet` — one row per person, `distinct_id` as first column,
feature columns named however the agent likes.

### `train.py`

```bash
python train.py <features.parquet> <labels.parquet> <model_out.pkl>
```text

Must print exactly one line of the form `holdout_auc: 0.XXXX` to stdout. The
framework parses that line.

`labels.parquet` is framework-generated. Schema: `(person_id, t0_ts, label, fold)`.
Agent does not write this — it is the output of `labeling.build_training_anchors_sql`
(today's logic, unchanged).

Agent writes whatever sklearn Pipeline it wants. Required: pickle a fitted
`sklearn.pipeline.Pipeline` (or compatible) to `model_out.pkl` via joblib. Must
pin `random_state` on any stochastic component.

Soft contract (prompt-enforced, not statically validated):

* Read labels and features, merge on `distinct_id`.
* Split by `fold`: train on `fold != 0`, evaluate on `fold == 0`.
* Print holdout AUC.
* Persist fitted Pipeline.

The framework will re-execute this at training-time to verify the claimed
holdout_auc (within tolerance) and again at every inference run.

### `predict.py`

```bash
python predict.py <features.parquet> <model.pkl> <scores.csv>
```text

Schema of `scores.csv`: `(distinct_id, p_y)`. Framework reads it and emits
`autoresearch_prediction` events from each row.

Same soft-contract approach: agent writes the file, framework's CI is "does it run
without crashing and produce a well-formed CSV."

### `recipe.yml`

Declarative metadata. The structured bits that stay structured so the UI can
display a comparable summary across champions:

```yaml
model_class: sklearn.ensemble.GradientBoostingClassifier   # informational, agent can use anything inside train.py
model_params:                                              # informational
  n_estimators: 200
  max_depth: 4
  learning_rate: 0.05
  random_state: 42
features:
  count: 17
  source_sql: features.sql
  lookback_days: 56
labeling:
  rule_version: random_t0_v1                              # which labeling.py logic produced labels.parquet
  horizon_days: 14
  training_lookback_days: 180
train:
  script: train.py
  expected_runtime_seconds: 30
predict:
  script: predict.py
agent:
  iteration_count: 4
  best_iteration: 4
  description: >
    Pageview prediction recipe with GBM. Top features are recency and
    upload frequency in the last 14 days.
```text

`model_class`/`model_params` are informational — the agent can use anything
inside `train.py` (custom transformers, ensembles, etc.). The yaml fields exist
so the UI can show a comparison table across champions without parsing the
script.

### `README.md`

Agent's plain-English narrative. Covers: what the agent tried, what worked,
what was discarded and why, top features and their interpretation, anything
operationally surprising. This is what a human reviewer reads first when
deciding whether to promote a challenger.

### `eda/iter-N-{slug}.ipynb`

One notebook per iteration. The agent writes it at the end of each iteration as
a summary of what was tried, the SQL queries it ran, key numbers it observed,
and a one-paragraph hypothesis. Next training run reads these to avoid retrying
discarded approaches.

Slug is a short human-readable description (`gbm-tuning`, `recency-features`,
`combined-iter1-iter3`).

### `requirements.txt`

A subset of the sandbox image's lockfile, listing only the packages
`train.py` and `predict.py` actually import. Lets laptop users install the
right deps locally with `pip install -r requirements.txt`.

## Execution paths

### Training-time

```text
Agent in sandbox:
  1. Reads prior champion via autoresearch-artifacts-get
  2. Iterates: writes features.sql + train.py drafts, executes locally in sandbox
  3. On each kept iteration: writes eda/iter-N-{slug}.ipynb via autoresearch-artifacts-upload
  4. On final winner: uploads features.sql, train.py, predict.py, recipe.yml,
     README.md, requirements.txt via autoresearch-artifacts-upload (one call per file)
  5. Calls autoresearch-training-runs-finalize with claimed holdout_auc

Framework on finalize:
  1. Materializes labels.parquet from labeling.build_training_anchors_sql
  2. Runs features.sql against training anchors → features.parquet
  3. Spawns sandbox with the autoresearch image
  4. Copies the artifact bundle + labels.parquet + features.parquet into sandbox
  5. Runs `python train.py features.parquet labels.parquet model.pkl`
  6. Parses `holdout_auc: ...` from stdout, compares to agent's claim
  7. If within tolerance: ingests as new champion (existing AutoresearchModel row creation)
  8. If not within tolerance: marks as failed with reason
  9. Cleans up sandbox
```text

### Inference-time

```text
Framework on scheduled scoring run:
  1. Materializes labels.parquet (same labeling rule as training)
  2. Runs features.sql against TRAINING anchors → train_features.parquet
  3. Runs features.sql against INFERENCE anchors → score_features.parquet
  4. Spawns sandbox
  5. Copies artifact bundle + both parquets into sandbox
  6. Runs `python train.py train_features.parquet labels.parquet model.pkl`
     ↑ this is the re-fit-every-run that gives the drift signal
  7. Runs `python predict.py score_features.parquet model.pkl scores.csv`
  8. Reads scores.csv, emits autoresearch_prediction events
  9. Cleans up sandbox
```text

The double sandbox spin-up at inference time is intentional. Cost is real but
bounded by sandbox cold-start (~30s with a warm pool, longer without). For v1
this is acceptable; we can add a warm-pool / model-cache layer later if cost
becomes a problem.

### Laptop-user-driven

```text
User on laptop:
  1. posthog autoresearch fetch-data <pipeline-id> --to ./run/
     → Creates a draft AutoresearchTrainingRun via autoresearch-training-runs-create
     → Downloads labels.parquet + features.parquet to ./run/

  2. (optional) posthog autoresearch fetch-artifacts <pipeline-id> --champion --to ./run/
     → Pulls the prior champion's artifacts as a starting point

  3. User edits train.py, features.sql locally. Runs `python train.py ...`.
     Iterates as they like.

  4. posthog autoresearch submit ./run/ --training-run-id <id> --holdout-auc 0.72
     → Walks the local files, calls autoresearch-artifacts-upload per file
     → Calls autoresearch-training-runs-finalize

  5. Framework runs the same verification path as the agent. If the recipe
     beats the current champion's holdout_auc, it becomes the new champion.
```text

The CLI is a thin wrapper over the MCP tools. Power users can call the MCP
tools directly.

## MCP surface

New tools:

```yaml
autoresearch-artifacts-upload:
  scopes: [autoresearch:write]
  input:
    training_run_id: uuid
    path: str            # e.g. "train.py" or "eda/iter-3-gbm.ipynb"
    content: str         # base64-encoded file body
  output:
    path: str
    size_bytes: int
    sha256: str

autoresearch-artifacts-list:
  scopes: [autoresearch:read]
  input:
    training_run_id: uuid
  output:
    paths: list[str]
    total_size_bytes: int

autoresearch-artifacts-get:
  scopes: [autoresearch:read]
  input:
    training_run_id: uuid
    path: str
  output:
    content: str         # base64-encoded
    size_bytes: int
    sha256: str

autoresearch-artifacts-delete:
  scopes: [autoresearch:write]
  input:
    training_run_id: uuid
    path: str
  output:
    deleted: bool

autoresearch-training-runs-finalize:
  scopes: [autoresearch:write]
  input:
    training_run_id: uuid
    holdout_auc: float
    agent_description: str
  output:
    status: str          # "running" once execution starts
    model_id: uuid | null
```text

Existing tools that change behavior:

```yaml
autoresearch-training-runs-create:
  # status now starts at "draft" (was "pending")
  # caller uploads artifacts, then finalizes

autoresearch-models-retrieve:
  # response gains a s3_path_prefix field for downloading artifacts
```text

## State machine

`AutoresearchTrainingRun.status`:

```text
draft → finalize → running → completed → (champion / challenger)
draft → finalize → running → failed (verification mismatch or train.py crash)
draft → (timeout, abandoned)
```text

`AutoresearchModel.role`:

```text
preliminary → champion (on promotion) → archived (when next champion lands)
```text

## Backwards compatibility

Existing `AutoresearchModel` rows with `model_recipe` JSON keep working. The
inference path detects format:

* If `model_recipe.feature_sql` is set and no `s3_path_prefix`, use the current
  inline `_score_via_anchors` path.
* If `s3_path_prefix` is set, use the new sandbox-execution path.

We don't migrate old recipes — they'll get superseded the next time the agent
runs and produces a winning new recipe under the new format.

## Open questions

These need a decision before implementation starts.

### Q1: Synchronous verification at finalize?

`finalize` runs `train.py` in a fresh sandbox to verify the agent's claimed
`holdout_auc` matches what the framework reproduces. This adds 1–3 minutes of
finalize latency.

Alternatives:

* **Async**: return immediately, run verification in a Temporal workflow,
  flip `failed` if mismatch.
* **Trust + lazy verify**: accept the claim, rely on realized AUC at horizon
  to surface fabricated AUCs.

**Lean**: Async verification. Finalize returns fast, sandbox spin happens in
the background, mismatch is logged + flagged but doesn't block UI. Realized
AUC at horizon is the ultimate truth.

### Q2: Upload size cap?

Single MCP call with base64 body works up to ~10MB before getting awkward.
Notebooks with embedded outputs can hit this.

Options:

* Cap at 10 MB per file, agent strips notebook outputs before upload.
* Implement chunked upload tool (`autoresearch-artifacts-upload-chunk`).
* Allow presigned-URL flow for large files (agent gets URL, PUTs directly).

**Lean**: 10 MB cap for v1, strip outputs in notebooks at upload time. Add
chunked upload later if hit.

### Q3: Sandbox image cadence

The autoresearch sandbox image bakes sklearn / pandas / numpy / jupyter at
specific versions. When we bump versions, existing recipes might break (sklearn
deprecates an API, model.pkl from old version doesn't load, etc.).

Options:

* **Single rolling image**: all pipelines share one image, breakage propagates.
* **Per-recipe pinned image**: each `recipe.yml` references an image tag,
  framework spins that tag. Insulates old recipes from version bumps.
* **N-back support**: framework keeps the last N image versions, prunes older.

**Lean**: Per-recipe pinned image. `recipe.yml` gains an `image_tag` field,
defaults to current at training time. Inference uses the recipe's tagged image.

### Q4: How does the agent's sandbox upload?

The sandbox already calls MCP tools via `posthog-exec`. The new upload tools
fit naturally. But base64-encoding multi-KB files inside a tool call requires
the agent to:

```python
import base64
content = open("train.py").read()
encoded = base64.b64encode(content.encode()).decode()
# call autoresearch-artifacts-upload via exec
```text

Workable but clunky. Two improvements:
* Add a sandbox-local helper script (`posthog-autoresearch-upload train.py`)
  that wraps the MCP call.
* Provide a Python SDK function in the sandbox image (`posthog_autoresearch.upload("train.py")`).

**Lean**: Both. Helper script for shell-mode agents, Python SDK for direct
use. The Python SDK is also what the laptop CLI wraps.

### Q5: Notebook format inside the artifact bundle

Jupyter `.ipynb` is canonical but heavy. Options:
* **Pure .ipynb** — round-trips with Jupyter UI cleanly.
* **Stripped .ipynb** — outputs and metadata stripped at upload to minimize size.
* **`.py` + paired `.md`** — script with markdown narrative, no native viewer.

**Lean**: stripped `.ipynb`. Outputs are reproducible by re-running, narrative is
preserved in markdown cells.

### Q6: Champion archival policy

Once a new champion ships, the previous champion's artifact bundle stays in
object storage. Cheap, but unbounded over time.

Options:

* Keep forever.
* Archive after N champions superseded (keep last 5 + current).
* Time-based: prune bundles older than 90 days.

**Lean**: Keep forever for v1, revisit if storage growth becomes meaningful.
History is genuinely valuable for the iteration log.

### Q7: `random_state` enforcement

Without a fixed `random_state` in `train.py`, every re-fit produces a slightly
different model — undermining the "refit as drift signal" framing because some
of the change is just RNG noise.

Options:

* Soft enforce via prompt only.
* Static validate `train.py` content for `random_state` reference.
* Pass `--random-state 42` as a framework-provided argument that `train.py`
  must accept.

**Lean**: Framework-provided arg. `python train.py features.parquet
labels.parquet model.pkl --random-state 42`. Agent doesn't pick the seed, the
framework does, and refits are deterministic across runs.

### Q8: Data-fetch MCP tool design

Laptop users need `labels.parquet` and `features.parquet` for the current
pipeline. We need an MCP tool that materializes those.

Options:

* `autoresearch-fetch-training-data(pipeline_id)` returns parquet bytes (huge).
* `autoresearch-fetch-training-data(pipeline_id)` returns a presigned download
  URL.
* Two tools: one to materialize, one to download.

**Lean**: Presigned URL. Materialization happens server-side (HogQL execution +
parquet write to object storage with short TTL), MCP returns the URL, laptop
CLI downloads via plain HTTP.

## Migration plan

A sketch of the implementation order, not yet committed:

1. Build the sandbox image with sklearn/pandas/numpy/joblib/jupyter pinned.
   Tag it, publish to internal registry.

2. Implement `autoresearch-artifacts-*` MCP tools backed by `object_storage`.

3. Implement `autoresearch-training-runs-finalize` and the new state machine.
   Async verification workflow in Temporal.

4. Implement `autoresearch-fetch-training-data` presigned-URL flow.

5. Build the laptop CLI (`posthog autoresearch fetch-data | submit`).

6. Rewrite the agent prompt to teach the new artifact layout + upload flow.

7. Rewrite the inference path to spawn sandbox + run `train.py` + `predict.py`.

8. Backwards-compat shim in inference for old `model_recipe`-JSON recipes.

9. UI updates: file browser for artifacts, notebook viewer, recipe.yml summary
   table.

10. Documentation + the laptop user guide.

## Changelog

* 2026-05-28: Initial draft (Andy + Claude session)
````
