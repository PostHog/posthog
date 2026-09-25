# Offline evaluation result reporting

The sandboxed evaluation harness in `products/posthog_ai/eval_harness/` reports scorer results as PostHog `$ai_evaluation` events.
With the Braintrust engine, each suite runs once and the harness sends the resulting scores to PostHog when uploads are enabled.
Reporting does not run the agent or scorers again.

## Capture settings

Evaluation result uploads to Braintrust and PostHog share the `no_send_logs` setting.
`SandboxedPublicEval` sets `no_send_logs=False` and uploads to both services.
`SandboxedPrivateEval` sets `no_send_logs=True` and uploads to neither service; local logs are still written.
The same settings apply to `WorkflowPublicEval` and `WorkflowPrivateEval`.
Private suites also disable the harness's PostHog agent traces, trace roots, and scorer tracing, even when other suites share an enabled trace client.
This setting does not control telemetry created by a workflow's own services or model clients; a private workflow must configure those separately.

The harness creates one dedicated result client at startup, shares it across all suites, and shuts it down after the invocation.
Each suite waits for queued PostHog uploads in worker threads so other suites can keep running.
This client permits `$ai_evaluation` reporting independently of `TEST` and `OPT_OUT_CAPTURE`, so those settings do not separate the two result destinations.
Ordinary PostHog SDK clients and trace clients retain their existing `TEST` and `OPT_OUT_CAPTURE` guards.

## Result contents and scope

Each event contains the existing experiment, case, and metric properties, including input, output, and expected values when available.
Result reporting uses the existing event schema.
The legacy SQL evaluation path in `ee/hogai/eval/offline/` has a separate reporter and is outside this behavior.

## Local trial artifacts

Every task invocation receives a unique `trial_id` and `artifact_dir` in its result metadata.
Sandboxed and workflow logs are stored under `logs/<experiment>/<run>/trials/<case>_<trial_id>/`, so repetitions cannot overwrite one another.
The directory stores the case input, available workflow output, and execution status and settings.
Completed cases also retain raw session logs, artifacts, and a readable summary.
After scoring, `result.json` retains the input, output, expected values, metadata, scores, and any infrastructure error.
Timeouts retain their timeout output; task exceptions retain their execution error and any logs already written.

`WorkflowEval` accepts `output_dir=Path(...)` to choose a different logs root, including a private artifact directory.
`WorkflowPrivateEval` accepts the same argument.
Choose private storage when case inputs or outputs contain historical project data.

A sandboxed case may set `project_data="empty"` when its setup hook restores saved inputs.
This creates a fresh organization, root project, and user without copying Hedgebox data or core memory.
The default remains `project_data="hedgebox"`.

## Private saved scout cases

Run from the repository root in the checkout that owns the evaluation.
Prepare that checkout's development environment and dependencies; do not use a Python environment or dependency executables from another worktree.
The commands below use its `.codex/with-flox` wrapper.
In a worktree with a newly provisioned wrapper, initialize it with `.codex/with-flox --prepare true` first.

The harness also needs the Python gateway's separate environment in this checkout.
Prepare those dependencies without starting another gateway:

```bash
.codex/with-flox env UV_PROJECT_ENVIRONMENT="$PWD/services/llm-gateway/.venv" \
    uv sync --project services/llm-gateway --frozen
```

The saved-case command loads this checkout's `.env`, preserving variables already supplied by the launch environment.
The wrapper builds a clean environment, so ambient exported credentials are not necessarily forwarded.
This checkout's ignored `.env` is a reliable place to supply them when using the wrapper.
The saved-case command does not load `.env.local` itself.
Provide `SANDBOX_JWT_PRIVATE_KEY` and `LLM_GATEWAY_ANTHROPIC_API_KEY`; Codex also needs `LLM_GATEWAY_OPENAI_API_KEY`.
The local signing key is available in `.env.example`.
Private saved cases do not require a Braintrust key.

Choose `SCOUT_EVAL_MODEL` and an explicit UTC `SCOUT_EVAL_CUTOFF` for the comparison, then check the inputs and execution prerequisites:

```bash
.codex/with-flox python -m products.signals.evals.saved_scout \
    --case /private/scout-case/case.json \
    --output-dir /private/scout-results \
    --target-cutoff "$SCOUT_EVAL_CUTOFF" \
    --agent-runtime codex \
    --agent-model "$SCOUT_EVAL_MODEL" \
    --reasoning-effort medium \
    --provider docker \
    --max-sandboxes 1 \
    --skill-delivery exec \
    --trials 1 \
    --preflight-only
```

`--preflight-only` validates the saved inputs, required environment variables, sandbox provider readiness, and the local gateway executable.
It rejects repository-backed cases with a provider other than Docker.
It does not initialize Django, prepare repository bundles, install dependencies, start services, or call a model.
Passing preflight does not prove model authentication, database readiness, free service ports, valid repository bundles, or available sandbox images.

Remove `--preflight-only` to execute the case; execution repeats these checks before initializing Django or preparing its repository.
Use the same runtime, model, effort, skill delivery, and cutoff for preflight and execution.
Before execution, coordinate use of the backing development services, eval ports, and test databases.
Separate worktrees still share those resources, so do not run the harness alongside another saved-case invocation or DB-backed pytest.
`--create-db` rebuilds the test database and is unnecessary for an ordinary repeat.

The JSON case manifest requires `schema_version: 2` and declares the saved skill, initial state, Parquet event files, source cutoff, and optional pinned repository.
It stores `state.checkpoint`, `state.complete`, `state.gaps`, and `state.timezone` inline.
The `events` list references Parquet files; `state.tables` maps each supplied history table to a Parquet file.
Every file reference contains its relative `path` and SHA-256 `sha256`, and must stay inside the case directory.

Supported history tables are `scratchpad`, `reports`, `report_artefacts`, `scout_notes`, `tasks`, `task_runs`, `scout_runs`, `metrics`, and `project_profile`.
Omit empty history tables; a supplied `project_profile` table must contain exactly one row.
The event list can be empty, and event files with the complete schema and zero rows are valid.
The [saved models](../../products/signals/evals/agentic/saved_case.py) define each table's columns.
The shared [Parquet reader and writer](../../products/signals/evals/agentic/saved_table.py) enforce column names, types, order, and nullability.
Timestamps use UTC with microsecond precision, UUIDs use strings, and flexible nested values such as event properties use JSON text columns.
The writer uses Zstandard compression.

The runtime reads only schema v2 Parquet tables and rejects JSON Lines, separate `state.json` payloads, and schema v1 manifests.
Convert older cases once with a local script into a separate private directory, preserving the original inputs.
The saved-case command has no conversion mode or compatibility reader.
Before using a converted case, compare every decoded event and history record with the original, then verify restoration in a fresh project.
These parity checks do not require model calls.

For fixed-file code cases, `repository.history_depth: 1` retains the original commit and complete tree without its ancestors.
Omit the depth when the scout needs retained Git history and the source checkout contains all required objects.
Keep private case files and results in ignored storage or outside the repository.
Use absolute paths when those inputs live outside the execution worktree.
The retained repository cache lives under `<output-dir>/repositories/`; a new output root prepares a separate cache.
`--validate-only` checks the manifest, hashes, Parquet schemas, record types, event records, and historical references without checking execution prerequisites.
It needs no model credentials or running Docker daemon and cannot be combined with `--preflight-only`.
Both check-only modes leave the output directory untouched.

The command uses the existing harness for service startup, fresh projects, production scout execution, concurrency, timeouts, and repetitions.
The private engine rejects uploads.
The command disables gateway capture tokens and routes both the scout and backend report checks through the private harness gateway.
Backend calls use a temporary scoped credential, which is removed when the suite exits.
Private data still goes to the configured model providers as part of scout execution and report checks.

Use the same target cutoff for every configuration and repetition in a comparison.
Restoration shifts typed timestamps and only the explicitly inventoried date strings.
The investigation interval includes its start and excludes its end.
This preserves elapsed-time relationships; it does not provide a historical clock or preserve all calendar-dependent behavior.

Each invocation retains its manifest and skill hashes, source commit and local changes, model settings, target cutoff, start and finish times, exit status, and full harness transcript.
Case metadata records `schema_version`, `manifest_sha256`, `state_table_sha256` by table name, and `event_sha256` in event-file order.
Execution attempts that fail the prerequisite checks retain this invocation history and transcript too.
Each trial has its own reports, scratchpad changes, session log, and execution result.
A skipped scout, failed task, or missing transcript fails the saved-case run.
Successful execution alone does not measure finding quality; reviewed references and a consistent rubric are separate inputs.

## Postgres experiment ingestion

The project API accepts offline experiment results behind the `ai-observability-offline-evaluations` feature flag.
The harness above still uses event capture; it does not call this API yet.

Use the base path `/api/projects/{project_id}/ai_observability/offline_experiments/`.

| Method and path                   | Purpose                                                                              |
| --------------------------------- | ------------------------------------------------------------------------------------ |
| `POST /`                          | Create an experiment with a caller-generated UUID, name, and `started_at` timestamp. |
| `POST /{experiment_id}/upload/`   | Persist one or many results and their shared items in one transaction.               |
| `POST /{experiment_id}/complete/` | Check any declared expected counts and close the experiment.                         |
| `POST /{experiment_id}/fail/`     | Close an interrupted experiment without requiring expected counts to match.          |

Programmatic callers use a personal or project secret API key with `offline_evaluation_ingestion:write`.
Project secret keys grant these operations across their project.
Personal keys and logged-in users require evaluation editor access.
They also require viewer access to the dataset when linking a revision or adding hosted items, and viewer access to the scorer definition when adding results.
Missing and inaccessible references return the same validation error.
Exact retries still acknowledge previously accepted records after reference access changes; they neither read payloads nor create new records.
The ingestion scope grants neither stored payload reads nor scorer administration.
Public project tokens used for event capture cannot authenticate these operations.

Create scorers first, using the existing scorer API or UI, and pin their version UUIDs before submitting results.
Older and archived versions remain valid references.
The API validates numeric bounds and steps, boolean values, and categorical keys against the pinned configuration.
Numeric scores use finite binary64 values; step validation allows rounding error of at most one millionth of the configured step.

For example, this upload declares one item and its boolean result:

```json
{
  "items": [
    {
      "id": "00000000-0000-4000-8000-000000000001",
      "payload": { "input": "What is 2 + 2?", "output": "4" }
    }
  ],
  "results": [
    {
      "item_id": "00000000-0000-4000-8000-000000000001",
      "scorer_version_id": "00000000-0000-4000-8000-000000000002",
      "status": "ok",
      "value": true
    }
  ]
}
```

The version UUID above is a placeholder for a pre-existing boolean scorer version.
An additional scorer result can reference the same `item_id` without repeating its item declaration or payload.
Each item declaration is complete and immutable.
Missing payload properties and explicitly supplied JSON nulls remain distinct.

Responses acknowledge committed writes and return stable item/result IDs, original acceptance times, and `created` flags.
Retries with the same identities and content return the original records.
Changed content returns HTTP 409; an invalid entry rejects the entire request with HTTP 400.
Validation responses include an `errors` array with a `code`, `detail`, and `attr` for each detected failure.
Field paths use zero-based request positions, such as `results.99.value` for the 100th result's score.
The top-level `code`, `detail`, and `attr` describe the first error for compatibility.
Request shape and field validation run before dataset and scorer validation; correct the reported errors and resend the batch to reach the next stage.
Within dataset and scorer validation, all entries are checked before rejecting the batch, and no new items, results, or payloads are stored.
Do not generate replacement item UUIDs when retrying a request.

Numeric scores allow a small floating-point rounding tolerance at minimum and maximum boundaries, so `7 * 0.1` is accepted with `max=0.7`.
The tolerance is capped at four floating-point units, `1e-12` absolute, `1e-12` relative to a nonzero boundary, and one millionth of the configured step when present.
Zero boundaries use a unit scale to allow small residues from subtraction.
Values outside that tolerance remain invalid, and accepted values are stored as submitted.

Optional `expected_item_count` and `expected_result_count` declarations are fixed at experiment creation.
Completion compares them with accepted unique counts, including error, skipped, and not-applicable outcomes.
A mismatch returns HTTP 409 with the expected and accepted counts and leaves the experiment uploading.
Repeated closure to the same state succeeds; changing a terminal state returns a conflict.
Closed experiments accept exact retries, but reject new items/results.

Uploads allow at most 1,000 results, 1,000 item declarations, and 5 MiB of request data.
Each item payload is limited to 1 MiB; each result payload to 256 KiB; JSON nesting to 32 levels.
Each upload must contain a result, and every declared item must be referenced by a result in that request.
Requests exceeding the body limit return HTTP 413.
Per-caller and shared project limits allow 60 requests per minute and 1,000 per hour; HTTP 429 responses include retry guidance.
The shared project limits apply across the parent project and all its child environments, regardless of which credentials each request uses.

The optional `run_source` accepts `ci`, `local`, `scheduled`, or null; empty strings are invalid.
For hosted datasets, set `dataset_revision_id` to the UUID of a hosted dataset revision when you create the experiment.
Each new item in that experiment must then set `dataset_item_version_id` to the UUID of an item version that is active in that revision.
Local and external datasets do not require hosted links; they can use the `*_identifier` fields instead.

Large payloads have separate storage and 30-day deadlines anchored to first acceptance.
Retries neither extend deadlines nor restore deleted payloads.
Automatic payload deletion and usage billing are not enabled by these endpoints.
