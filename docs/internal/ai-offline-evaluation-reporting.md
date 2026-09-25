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

The case manifest declares the saved skill and its file hashes, initial state, optional compressed event files, source cutoff, and optional pinned repository.
For fixed-file code cases, `repository.history_depth: 1` retains the original commit and complete tree without its ancestors.
Omit the depth when the scout needs retained Git history and the source checkout contains all required objects.
Keep private case files and results in ignored storage or outside the repository.
Use absolute paths when those inputs live outside the execution worktree.
The retained repository cache lives under `<output-dir>/repositories/`; a new output root prepares a separate cache.
`--validate-only` checks the manifest, hashes, record types, event records, and historical references without checking execution prerequisites.
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
Execution attempts that fail the prerequisite checks retain this invocation history and transcript too.
Each trial has its own reports, scratchpad changes, session log, and execution result.
A skipped scout, failed task, or missing transcript fails the saved-case run.
Successful execution alone does not measure finding quality; reviewed references and a consistent rubric are separate inputs.
