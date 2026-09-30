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
Provide `SANDBOX_JWT_PRIVATE_KEY`, `LLM_GATEWAY_ANTHROPIC_API_KEY`, and `LLM_GATEWAY_OPENAI_API_KEY`.
The OpenAI credential serves rubric generation and judging even when the scout uses Claude.
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

### One rubric per scout per session

`--output-dir` identifies a persistent comparison session, including invocations from later commands.
The first invocation for a scout automatically generates its rubric from the saved scout instructions and reference files.
It uses the same draft, selection, and format-repair implementation as the scout rubric generator.
The script adopts the selected suggestions alongside the standard criteria and saves the result under `rubrics/`.
Generation receives no evaluated outputs or hidden reference findings.

Every model, prompt variant, and repeat for that scout in the same session uses the exact saved rubric and canonical instructions.
Each result and judgment records the rubric SHA-256.
The first generation holds a file lock, so concurrent requests cannot select different rubrics.
A changed or missing pinned rubric fails rather than regenerating during the comparison.
Keep the rubric JSON and its lock file together; use a new output directory to start a session with new criteria.
Different scouts keep separate rubrics in the same session.

Generation defaults to `gpt-6-sol` and judging to `gpt-6-astra`, both at high reasoning effort and independently of the model being evaluated.
`--rubric-model` applies only to the first generation; changing it does not replace an existing session rubric.
`--judge-model` selects the judging model, which is recorded with its responses and usage.
Use the same judging model across a comparison.
`--rubric-only` prepares or reuses the session rubric without restoring project data or launching a scout:

```bash
.codex/with-flox python -m products.signals.evals.saved_scout \
    --case /private/scout-case/case.json \
    --output-dir /private/scout-results \
    --rubric-only
```

Normal execution then restores the case, runs the scout, and judges the retained result automatically.
The shared generator's pure schemas and generation logic live in `products/signals/backend/rubrics_schema.py`
and `products/signals/backend/rubrics_generation.py`; production authorization and persistence remain in the scout harness.

Judgments use the scout trial response contract: a `summary` and one `criteria` entry per enabled criterion.
Each entry contains `criterion_id`, `verdict`, `reason`, `confidence`, and evidence with `source_id` and an exact `quote`.
Verdicts are `pass`, `fail`, `unknown`, or `not_applicable`; confidence is `low`, `medium`, or `high`.
The pure schemas, versioned prompts, citation validation, and scoring live in `products/signals/backend/rubrics_judging.py`.

Invalid evidence quotations or conclusions citing only candidate instructions become `unknown` for that criterion.
Other valid criteria remain available. Missing historical evidence does not become a failed criterion.
Malformed or incomplete model responses are run-level `judge_error` results with no quality verdicts.
Failed or unconfirmed scout executions are `excluded`; execution failures and judge errors do not receive scores.
Judging makes one request and does not automatically repair or retry it.

The score is `pass / (pass + fail)`. Coverage is `(pass + fail) / (pass + fail + unknown)`.
An empty denominator produces `null`; `not_applicable` is excluded from both denominators.
Read score and coverage together: a high score with low coverage is not a complete evaluation.
Incomplete judgments cannot establish a baseline difference.
Detailed private judgment files retain the original model response, normalized verdicts, usage, rubric/reference hashes,
judge model, prompt version, and evidence provenance. Dollar costs remain unknown when the model route does not provide them.
New judgments use artifact version `scout-rubric-judge-v4`; earlier files stay untouched.
To evaluate an older run under the current contract, rejudge its original `result.json` into a new judgment file.

Judging uses the retained transcript and state, not fresh project queries or an exhaustive answer key.
An exact evidence quote establishes where text came from, not that its claim is correct.
Valid citations also do not establish that the judge interpreted a criterion correctly; compare decisions with examples reviewed by a person.
Local records and transcript entries receive stable source IDs. Their original file locations and JSON pointers remain in provenance.
Candidate instructions are marked as instruction sources; the frozen rubric reference is separate from execution evidence.
Quotes and newlines remain intact, and the offline evidence adapter preserves the complete capture.
The judgment records the evidence adapter version and original output and transcript hashes.
`--judge-max-input-tokens` sets a proxy token budget (default 900,000); the script retains an explicit ungraded error
when evidence exceeds the budget or byte limit, rather than silently dropping evidence.
The budget is not a guarantee that a different judging model accepts the same context size.

### Judge saved runs

Use the same session directory to judge existing `result.json` files without rerunning scouts or modifying the originals:

```bash
.codex/with-flox python -m products.signals.evals.saved_scout \
    --case /private/scout-case/case.json \
    --output-dir /private/scout-results \
    --judge-results /private/previous-run/trials/case_trial/result.json
```

`--judge-results` accepts multiple files for the same scout.
It reuses the pinned rubric, or generates it once if the session has none.
`--rubric-only` and `--judge-results` validate the manifest and the saved skill/reference files, including their paths,
checksums, and UTF-8 contents. They do not load or validate saved state or event tables, which are not inputs to these modes.
Their provenance records `validation_scope: instructions`; it does not claim that the case can be restored.
Normal execution, `--validate-only`, and `--preflight-only` still require the complete case to pass strict validation.
Historical judgments use the cutoffs and evidence recorded in each result; `--target-cutoff` does not shift saved results.
Failed historical executions remain `excluded`, with no quality verdicts or scores.
New judgment files record both the source-result hash and the session-rubric hash.
These modes use the shared private eval service lifecycle, so its ordinary environment prerequisites still apply.
They do not launch scout tasks or restore case events.

### Execution environment

Before execution, coordinate use of the backing development services, eval ports, and test databases.
Separate worktrees still share those resources, so do not run the harness alongside another saved-case invocation or DB-backed pytest.
`--create-db` rebuilds the test database and is unnecessary for an ordinary repeat.
Keep the execution checkout and saved inputs unchanged until the invocation finishes.
The MCP development server reloads when its source changes; the recorded source hashes describe the start of the invocation, not changes made during it.

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
It also overrides inherited MCP analytics credentials with empty values so the tool service cannot capture private tool inputs or results.
Backend calls use a temporary scoped credential, which is removed when the suite exits.
Private data still goes to the configured model providers as part of scout execution and report checks.

Before launching a scout, restoration queries HogQL to verify event counts and timestamp bounds in the new project.
An empty case must return no events; a failed query is an infrastructure error, not evidence that the project is empty.

Use the same target cutoff for every configuration and repetition in a comparison.
Restoration shifts typed timestamps and only the explicitly inventoried date strings.
The investigation interval includes its start and excludes its end.
This preserves elapsed-time relationships; it does not provide a historical clock or preserve all calendar-dependent behavior.

Each invocation retains its manifest and skill hashes, source commit and local changes, model settings, target cutoff, start and finish times, exit status, and full harness transcript.
Case metadata records `schema_version`, `manifest_sha256`, `state_table_sha256` by table name, and `event_sha256` in event-file order.
Execution attempts that fail the prerequisite checks retain this invocation history and transcript too.
Each trial has its own reports, scratchpad changes, session log, and execution result.
The runner waits for the task workflow to terminate before collecting final state and logs, then cleans up that task's sandbox.
Artifacts record the scout result, persisted task status, and workflow completion separately.
A task marked completed does not count as a successful execution if workflow termination cannot be confirmed.
Cancellation and transcript-processing errors retain the output already collected for diagnosis.
A skipped scout, failed task, or missing transcript fails the saved-case run.
Successful execution alone does not measure finding quality; inspect rubric judgments and their evidence coverage separately.
The saved-case generator and judge use the existing local, test-only gateway context, with temporary eval-database
personal keys and capture disabled. The Go gateway does not support those `phx_` credentials; this is the existing
eval caller's temporary authentication exception, not a separate production gateway route.
Both backend and sandbox Go-routing settings are suppressed inside the private context and restored afterward.
Gateway accounting remains enabled.

## Saved datasets through online comparisons

`products.signals.evals.saved_comparison` connects saved Parquet cases to the production comparison engine.
The shared private workflow harness owns local services and cleanup; the online workflows own variant launches,
repeats, automatic judging, and comparison reports. This does not start the periodic scout fleet coordinator.
The initial integration still needs a live one-scout, two-variant pilot; passing input validation does not establish
provider access, tool isolation, successful judging, or cleanup.

Write a private plan with the saved skill name. The first variant is the baseline. This example uses invented scout data:

```json
{
  "schema_version": 1,
  "comparisons": [
    {
      "skill_name": "signals-scout-checkout-example",
      "variants": [
        { "label": "Baseline", "model": "gpt-5.5", "reasoning_effort": "medium", "repeats": 1 },
        { "label": "Higher effort", "model": "gpt-5.5", "reasoning_effort": "high", "repeats": 1 }
      ]
    }
  ]
}
```

Choose one explicit UTC target cutoff for the entire batch, then validate the plan and saved inputs:

```bash
.codex/with-flox python -m products.signals.evals.saved_comparison \
    --case /private/scout-cases/checkout/case.json \
    --plan /private/scout-cases/comparison.json \
    --output-dir /private/scout-comparisons \
    --session-dir /private/scout-session \
    --target-cutoff "$SCOUT_EVAL_CUTOFF" \
    --provider docker \
    --agent-runtime codex \
    --agent-model gpt-5.5 \
    --max-sandboxes 2 \
    --skill-delivery exec \
    --trials 1 \
    --validate-only
```

Remove `--validate-only` to execute. Validation checks and merges saved inputs in a temporary directory without
restoring a database, starting services, or calling a model. Execution repeats validation and the saved-case
prerequisite checks. Docker is currently required. Set repetitions in the plan; `--trials` must remain `1`.
Variants in one comparison run in parallel, so `--max-sandboxes` must cover their total repeats, up to 20 runs.
Comparisons for different scouts run sequentially. Harness runtime/model options configure bootstrap;
the plan selects each variant's actual model and effort. The online service validates supported combinations.
An optional variant `instructions` file uses the saved-file shape (`path` and `sha256`), relative to the plan.

Repeat `--case` for different scouts captured from the same source project, source cutoff, state checkpoint,
timezone, and reviewed text replacement policy. The adapter merges identical records and rejects conflicting IDs,
different snapshots, and incomplete reference graphs. All cases in a batch must use one retained repository snapshot.
The merged dataset is restored once into one fresh eval project with one timestamp shift and identity mapping.
Each comparison freezes its starting history; each run keeps separate private report and memory changes.
The adapter checks shared reports, report artifacts, notes, and memory after each comparison and fails if they changed.
An explicit cutoff preserves elapsed-time relationships; it does not freeze application time or all relative queries.
Prepare scouts with relative time windows when their dataset will be shifted. Absolute dates in the frozen rubric
or canonical instructions remain requirements; the run note does not translate those requirements for the judge.
The adapter rejects a declared time-string replacement that would change those frozen requirements.
Other absolute-date requirements still need review before comparing scores against a shifted dataset.

`--session-dir` defaults to `--output-dir`. Rubrics are generated once per scout in that session and reused across
variants, repeats, and later invocations. `--rubric-model` only affects the first generation. The adapter installs the
frozen criteria and generator reference into the isolated project, then uses the online rubric completeness checks.
This automatic adoption is limited to `TEST` plus `DEBUG`; the ordinary online editor still requires an explicit save.
Candidate instruction files do not replace the frozen rubric reference.

The adapter uses the online judge's model, versioned prompt, bounded evidence extraction, normalization, and scoring.
Both judge paths import their schema, prompts, validation, and score calculations from `products/signals/backend/rubrics_judging.py`.
It does not use the standalone saved-case judge's model or full-evidence input policy. Complete raw task logs and
private run state are exported separately, alongside the frozen context, rubric hash, judge input, comparison result,
dataset hashes, source commit, local patch, and invocation settings. Evidence limits remain visible in the online report;
retaining full logs does not make the bounded judgment complete. Read coverage and inconclusive outcomes with scores.
Inputs and artifacts stay in private storage, but scout execution, rubric generation, and judging send content to the
configured model providers.

The adapter scopes `SCOUT_LIVE_TRIALS_LOCAL_PROJECT_IDS` to the newly restored project while its worker runs.
This empty-default allowlist only applies with `DEBUG`; staff, active membership, project/skill access,
operator ownership, and task-token binding remain required. Explicit fleet allowlists, drain-all or skip decisions,
daily limits, and spend gates still apply. The CLI uses the service directly; frontend project visibility is unchanged.

## Live scout comparisons

For a synthetic local environment, follow the [devbox setup and quality iteration handoff](scout-online-evals-devbox.md).

Live scout trials use the production scout harness and live project reads, with private memory changes and captured reports.
They do not use the offline evaluation reporter or its `no_send_logs` switch.
Launches are disabled unless `SCOUT_LIVE_TRIALS_ENABLED` and `SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE` are enabled.
Trials use the existing Python model gateway through the normal `LLM_GATEWAY_URL` and `SANDBOX_LLM_GATEWAY_URL` settings.
No additional gateway service or capture destination is required.
The gateway identifies trial requests from server-minted, task-bound Signals OAuth credentials and suppresses their generation, exception, and rate-limit denial events.
Backend report validation and comparison judging use short-lived credentials with only gateway access and the experiment identity; each credential is revoked after the operation.
Ordinary gateway requests keep their capture behavior, and trial requests retain cost and rate-limit checks.

Deploy the gateway change before enabling trials on the backend and workers.
`SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE` attests that the deployed gateway supports this policy and that query/task telemetry and warehouse replicas do not expose trial content to the project the scouts inspect.
This setting does not configure or detect gateway support automatically.
Trials keep the Python route and reject subscription credentials; the Go migration requires the same capture policy and support for the selected models.
Shared generation events cannot supply trial costs when capture is suppressed.
Results report unknown cost as null and retain runtime token counts when available.
Trial credentials can upload logs and update the summary, status, usage and agent version of their own verified run without general task-write access.
Failure callbacks can record the error and agent version together; they cannot change protected state or another run.
Operator trial MCP tools also omit analytics payloads.
Task content retrieval tools retain call metrics but omit content spans and free-text intent, so viewing a private transcript does not publish it through MCP analytics.

Private trial tasks, logs, artifacts, and controls are available only to the launching operator or the sandbox bound to that task.
Other project members do not discover them through ordinary task lists or searches, and trial ownership cannot be transferred.
Polling preserves the runner's saved completion outcome, including cancellation, and reports the underlying task status separately.
A trial stopped through the task controls records cancellation even when the agent has no final message or only an earlier partial response.
A poll can recover a missing export without replacing an existing result.

Trials cannot create or cancel report follow-up checks, or record their results. Check lists are unavailable for newly emitted private reports; the API returns an explicit capability error without invalidating the trial. Existing checks on live reports remain readable, including when the trial has privately edited that report. The trial prompt directs planned follow-up to private scratchpad entries.
Private report writes must omit typed report links. Nonempty `links` on either an emit or edit are rejected before target lookup or judging and make the run ineligible for comparison. Ordinary report emissions retain link persistence and autostart gating.
Private inbox lists support `count_only` and `include_source_metadata` like ordinary inbox lists. Opting out of source metadata applies to live reports, private edits and newly emitted private reports without invalidating the trial.

Individual skill reads and markdown downloads serve the run's pinned candidate.
Trial sandboxes can use stub skill bundles, which fetch each skill through those reads.
Full-content bundles are rejected because they cannot apply the run's private candidate; ZIP exports remain unavailable to scoped trial credentials.

The [live comparison plan and script](../../products/signals/eval/experiments/2026-09-long-running-agent-evals/PLAN.md#live-trial-operator-script) describe launch inputs, stored results, and supported scout capabilities.
Keep downloaded prompts, memory, reports, and transcripts outside version control.

### Reviewed scout rubrics

New comparisons use `rubric_source: saved` and read the scout's reviewed rubric through the existing team-scoped rubric service.
Generate suggestions in the rubric editor, review the proposed checks and their reference instructions, and explicitly save the selection before scoring.
Revision zero contains unsaved defaults and cannot be scored, even when suggestion generation has completed.
Only enabled saved `criteria` are judged; `generation.suggestions` remain drafts until selected and saved.
Scoring never generates a rubric or falls back to the mock fixture.

The saved rubric binds its criteria to the reference instructions, description, report rules and reference files captured during generation.
Editing the scout, its references or a comparison candidate does not change that checklist.
Only an explicit saved rubric update changes what future evaluations use.
Rubrics without saved references, or with omitted or truncated reference content, must be regenerated, reviewed and saved before scoring.

Starting a comparison freezes the full rubric document, enabled criteria, saved revision and governing references before launching scouts, so every variant uses the same requirements.
Editing the saved rubric while a comparison runs does not change its grading checklist.
The report and JSON export retain the frozen references and their generation identity for inspection.
The [mock fixture reader](../../products/signals/backend/scout_harness/trial_rubrics.py) remains available for offline development.
Existing mock snapshots and reports remain readable, and exact-ID retries reuse their saved request; a new evaluation ID requires the saved rubric.

### Saved scoring and reports

Starting a comparison includes scout execution and automatic judging, both of which incur model charges.
The server waits until all selected runs reach a known terminal state before judging their saved evidence.
The separate scoring endpoint remains available for existing runs and deliberate new scoring attempts.
The request names a baseline and variant groups, with at most 20 distinct launches from the same scout, operator and saved starting context.
Runs within a variant must use the same instructions, note, model, runtime, reasoning effort and service tier.
The server freezes the rubric, bounded evidence, judge model and prompt version before dispatching the judge.
Evidence includes instructions, starting history, captured reports, memory changes, summaries and available tool calls and results.
Missing or truncated evidence is recorded as a limitation; private thoughts and reasoning are excluded from the extracted trace.
Session titles and other recognized metadata updates are not tool evidence; unknown event formats still produce coverage limitations.
Trace extraction removes exact repeated updates and duplicate output content, then shares the available evidence budget across the retained tool events in their original order. Verbose early output cannot consume the space reserved for later results; source-count and size limits remain explicit limitations.
Tool trace fields use labelled text blocks that preserve string values, including quotes, line breaks and literal backslashes. This lets the judge quote returned prose without copying an extra layer of JSON escaping. Call identity, status, errors and inputs remain part of the same bounded source.

The judge receives criteria, the fixed reference context and run evidence without variant labels or scout model settings.
Candidate instructions and starting-context notes cannot remove or relax the saved rubric's requirements.
Editable launch notes are instructions, so quoting their claims alone cannot prove execution. Saved starting history can establish applicability, but cannot prove actions taken in the evaluated run.
Reference instructions define the requirements but cannot serve as evidence that the scout performed them.
The complete judge input must fit the existing 120,000-character limit before dispatch; scoring rejects oversized inputs with an actionable error instead of truncating governing requirements or starting a paid call.
It returns one verdict per criterion: pass, fail, unknown or not applicable.
Pass, fail and not applicable require source references and exact quotations from the saved evidence.
Unverifiable citations become unknown, and quoting an instruction alone cannot prove it was followed.
When validation makes a verdict unknown, it replaces the model's summary with a notice to review the criterion results and validated evidence.
Versions 6 through 8 distinguish missing source IDs, blank or mismatched quotations, instruction-only evidence and missing citations in the normalized reason. These reasons contain no rejected quotations or raw model output.
New evaluations record judge version 8. A pass needs evidence for every applicable mandatory requirement and material claim. Explicit scope violations fail even when the returned counts look plausible; missing proof produces unknown. Lower confidence or a causal disclaimer cannot substitute for that proof. Supported composite record descriptions can identify sources, and incidental details do not defeat a criterion about material claims.
Count claims must follow the query and observed identifiers: an aggregate alias or a distinct count of placeholder identifiers does not establish real users or entities. Citations must use the envelope's source IDs and exact text, decoding only the outer input envelope when copying embedded JSON or escaped strings.
Version 8 uses high reasoning effort, at most 24,000 completion tokens per run, and a 240-second request timeout. It disables retries both in the caller and in the gateway's native OpenAI provider transport. Version 7 retains its 16,000-token limit and versions 1 through 6 retain their 8,000-token limit. Limit failures retain usage but no partial verdicts; versions 7 and 8 explain that the rubric size may need review. The 64,000-character verdict-document limit is unchanged.
Pending versions 1 through 7 retain their original prompts, evidence envelopes, citation normalization and request limits. Versions 5 through 7 continue to use their separate, fixed reference context; previously saved snapshots and reports remain unchanged.
Missing evidence is unknown; not applicable means the criterion does not apply to that run.
The judge assesses the saved text and does not independently verify external sources or measure recall.

A run's score is `pass / (pass + fail)`, or null when it has no decisive verdicts.
A variant's score is the equal mean of its non-null run scores.
Coverage is `(pass + fail) / (pass + fail + unknown)`; not applicable is excluded from both score and coverage denominators.
Execution exclusions and judge errors have no quality score and are counted separately.
A scout runner failure remains an execution exclusion even if its sandbox task completed; the saved trial outcome records the runner failure.
Reports retain each run's verdicts, reasons, quotations and evidence limitations alongside aggregate counts.
Baseline differences are withheld unless all selected runs were judged with complete, comparable verdicts.
New reports include a best variant, a tie, or an inconclusive result, with an explanation.
The best variant passes the most rubric checks across repeated runs. Each check has equal weight; cost and speed do not affect the result.
A winner requires at least two variants, equal repeat counts, and complete judgments on the same applicable checks.
Unknown verdicts, excluded runs, judge errors or different applicability make the conclusion inconclusive, even when a displayed pass rate is high.
These conclusions describe the captured runs; they do not establish statistical significance or guarantee results on other data.
Historical reports without a saved conclusion remain readable without inventing one.
Shared starting history does not freeze the live project data read during each run.

Start a comparison with `POST /api/projects/{team_id}/signals/scout/configs/{config_id}/trial_comparison/`.
Under the same scout URL, `trial_comparison_result/` reads its status and report, and `trial_comparison_history/` lists the operator's saved comparisons.
`POST trial_comparison_resume/` recovers the same saved work without creating fresh scout runs or repeating claimed judge calls.
Separate scoring of existing runs uses `POST /api/projects/{team_id}/signals/scout/configs/{config_id}/trial_evaluation/`.
Read the saved outcome with `GET /api/projects/{team_id}/signals/scout/configs/{config_id}/trial_evaluation_result/?evaluation_id=...`.
Reuse an evaluation ID only for the same request; a different request with that ID is rejected.
Retries reuse saved work and do not repeat an attempted judge call automatically.
Rate-limited judge calls retain an error with guidance to wait or check usage limits before starting a new evaluation. Scoring credentials remain bound to the scout task, so repeated evaluations also consume that task's gateway allowance.
Polling reads the saved status or report without starting model calls.
Every read remains restricted to the operator's current project and skill access.

### Internal comparison UI

Staff members in project 2 can open **Scouts > Compare scouts** to choose a scout, add prompt/model/effort variants, and set the number of runs per variant.
The page submits one comparison containing at most 20 runs and shows deployment or scout compatibility blockers before launch.
The server saves the variants, reviewed rubric and shared starting history before dispatch. Each run keeps its own private writable state.
Once the comparison is accepted, execution and judging continue after the page closes.
Progress distinguishes starting, running scouts, judging and completed results. Reloading reads saved state without starting another paid attempt.

The current comparison is separate from the operator's run history. Active runs can be stopped; captured reports, memory changes and available usage can be exported as JSON.
The report leads with the comparison conclusion and variant results. It shows average pass rates and counts of passed checks, failed checks and checks without enough evidence.
Counts across repeated runs count each execution's checks, rather than distinct rubric definitions. Not-applicable checks remain separate.
Individual runs are grouped by variant. Each run has compact criterion name/status rows; expand a criterion to read its explanation and supporting quotations.
Saved rubric definitions, captured reference instructions and raw evidence remain available as supporting details.
An explicit new judging attempt can reuse completed scout runs with the current saved rubric while keeping the old report available. It may charge for judging every run again.
Browser storage keeps only scout, comparison, variant, baseline and launch IDs, scoped to the project and operator; prompts, labels, evidence and reports stay out of browser storage.
Unsubmitted prompt edits are lost on reload. Accepted comparison plans and their status are recovered from the server.
The setup, history and scoring endpoints enforce the staff/project restriction on the server, in addition to existing scout permissions.
Shared instructions guide investigations but do not enforce date or file access limits.

## Postgres experiment ingestion

The project API accepts offline experiment results behind the `ai-observability-offline-evaluations` feature flag.
The harness above still uses event capture; it does not call this API yet.

Experiments and their items, results, and payloads belong to the exact project/environment in the request path.
Scorers and hosted datasets must belong to that same environment.
Parent, child, and sibling environments do not share experiment data.
Existing stored rows retain their current ownership.

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

## Postgres experiment reads

Read endpoints use the same feature flag as ingestion.
The existing event-based offline UI and harness remain separate until they switch to these APIs.

The following GET paths are relative to `/api/projects/{project_id}/ai_observability/`:

| Path                                                               | Response                                                                             |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| `offline_experiments/`                                             | Experiments, run context, lifecycle state, and counts.                               |
| `offline_experiments/{experiment_id}/`                             | One experiment, regardless of list date filters.                                     |
| `offline_experiments/{experiment_id}/items/`                       | Item metadata, payload availability, and optionally selected scorer-version results. |
| `offline_experiments/{experiment_id}/items/{item_id}/`             | One item's metadata and payload availability.                                        |
| `offline_experiments/{experiment_id}/items/{item_id}/results/`     | The item's results with pinned scorer configurations.                                |
| `offline_experiments/{experiment_id}/items/{item_id}/payload/`     | Shared input, output, expected output, and item metadata.                            |
| `offline_experiments/{experiment_id}/results/{result_id}/payload/` | One result's reasoning, error details, and metadata.                                 |
| `offline_experiments/{experiment_id}/scorer_summaries/`            | Summaries grouped by exact scorer version.                                           |
| `offline_scorers/{definition_id}/history/`                         | Experiment summaries for one stable scorer definition.                               |

Reads accept logged-in sessions and personal API keys.
Experiment and item metadata, including shared item payloads, require `evaluation:read` and evaluation viewer access.
Results, result payloads, summaries, history, and scorer filters also require `llm_analytics:read` and viewer access to the corresponding scorer definitions.
An upload-only credential cannot read stored results or payloads.
Project secret API keys remain limited to the ingestion and lifecycle operations above.
Reads allow 600 requests per minute and 6,000 per hour per caller, with shared project limits of 3,000 per minute and 30,000 per hour.
These limits are separate from ingestion so fetching individual payloads does not consume the upload budget.
The shared read budget includes child environments of the same parent project.

Experiment responses expose `accepted_item_count` separately from `visible_result_count`, `visible_scorer_definition_count`, and `visible_scorer_version_count`.
Visible counts include only authorized scorers and are marked with `result_count_scope: "authorized"`.
For personal keys without `llm_analytics:read`, these three counts are null and `result_count_scope` is `"unavailable"`.
Declared expected counts remain caller-supplied totals, so they are not a measure of the reader's visible result coverage.
Missing and inaccessible scorer references produce the same response.

Paginated responses contain `count`, `next_cursor`, and `results`.
Use `limit` to request between 1 and 100 rows; the default is 50.
Pass `next_cursor` back as `cursor`, keeping the same filters, to continue.
Unsupported filters, duplicate query parameters, and selections over the limit return HTTP 400.
Experiment and history ordering follows execution time with stable identity tie-breakers; server receipt times remain separate fields.
Uploading experiments can change between requests, so their pages are a live view.

Experiment lists and scorer history support execution-time filters (`date_from`, `date_to`), name search (`search`), run source, lifecycle states (`statuses`), suite key, dataset source and identifiers, application/model/prompt versions, and exact scorer versions.
Experiment lists also accept `scorer_definition_id`; history uses the scorer definition in its URL and rejects that query parameter.
The date range includes `date_from` and excludes `date_to`; `statuses` accepts comma-separated `uploading`, `completed`, and `failed` values.
Use `run_source=not_specified` to select runs without a source.
Experiment lists include all lifecycle states by default; scorer history includes completed experiments unless other states are selected explicitly.
Filters use retained identifiers and continue to work after linked resources are deleted.

Item pages can include result cells for up to 20 comma-separated `scorer_version_ids`.
The page's `scorer_versions` list contains each selected, accessible version's metadata and configuration once, including versions with no results on the page.
Item result cells link to that list with `scorer_version_id`.
Version selection preserves unscored items, which have missing cells.
Use the paginated item results endpoint to inspect additional versions; it includes full scorer metadata and configuration on each result.
List and summary endpoints do not load input/output or reasoning payloads.

## Scorer versions and summaries

Discover immutable versions through `GET /api/projects/{project_id}/llm_analytics/score_definitions/{definition_id}/versions/`.
Retrieve a specific version at the same path followed by `{version_id}/`.
These operations use the existing scorer read permissions and include historical versions without recent results.
Archived scorers remain addressable, including their versions and offline history, while default scorer selection excludes them.
Creating another version with an unchanged configuration remains supported.

Experiment summaries and scorer history use the same aggregation rules over all matching results, independently of item pagination or payload availability.
Different scorer versions remain separate, even when their configurations match.

| Kind        | Summary                                                                                |
| ----------- | -------------------------------------------------------------------------------------- |
| Numeric     | Mean of successful values and the successful sample count.                             |
| Boolean     | True and false counts, with the true rate among successful results.                    |
| Categorical | Counts and rates per key from the pinned version, including keys with no observations. |

Multiple-selection category rates divide by the successful result count and can add up to more than 100%.
Error, skipped, and not-applicable outcomes are counted separately and excluded from value summaries.
No successful results produces a null mean or rate.
Missing results among observed items are reported separately and do not indicate how many entirely absent items were intended.
Each repeated trial contributes one item; summaries also expose case and trial coverage without applying per-case weighting.
Numeric increases and boolean true do not imply better quality unless that meaning is established by the scorer.

## Reading payload availability

Items and results expose their own `payload_state` and `payload_expires_at`.
Payload detail responses include `available` and `data`, preserving omitted properties, empty objects, and explicit JSON null values.
`not_provided` means the caller omitted the payload; `expired` means it was removed while its owner was retained.
An unavailable payload has null `data`, while durable identities, results, and summaries remain readable.

A deadline alone does not mean a cleanup worker has removed the payload.
Automatic deletion remains separate work.
Expired input/output is not reconstructed from linked datasets or traces, and missing links do not prevent experiment reads.
Opening those resources requires their own permissions.
