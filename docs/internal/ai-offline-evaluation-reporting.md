# Offline evaluation result reporting

The sandboxed evaluation harness in `products/posthog_ai/eval_harness/` reports scorer results as PostHog `$ai_evaluation` events.
With the Braintrust engine, each suite runs once and the harness sends the resulting scores to PostHog when uploads are enabled.
Reporting does not run the agent or scorers again.

## Capture settings

Evaluation result uploads to Braintrust and PostHog share the `no_send_logs` setting.
`SandboxedPublicEval` sets `no_send_logs=False` and uploads to both services.
`SandboxedPrivateEval` sets `no_send_logs=True` and uploads to neither service; local logs are still written.

The harness creates one dedicated result client at startup, shares it across all suites, and shuts it down after the invocation.
Each suite waits for queued PostHog uploads in worker threads so other suites can keep running.
This client permits `$ai_evaluation` reporting independently of `TEST` and `OPT_OUT_CAPTURE`, so those settings do not separate the two result destinations.
Ordinary PostHog SDK clients and trace clients retain their existing `TEST` and `OPT_OUT_CAPTURE` guards.

## Result contents and scope

Each event contains the existing experiment, case, and metric properties, including input, output, and expected values when available.
Result reporting uses the existing event schema.
The legacy SQL evaluation path in `ee/hogai/eval/offline/` has a separate reporter and is outside this behavior.

## Live scout comparisons

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
Trial credentials can upload logs and update the summary, status, and usage of their own verified run without general task-write access.
Operator trial MCP tools also omit analytics payloads.
Task content retrieval tools retain call metrics but omit content spans and free-text intent, so viewing a private transcript does not publish it through MCP analytics.

Private trial tasks, logs, artifacts, and controls are available only to the launching operator or the sandbox bound to that task.
Other project members do not discover them through ordinary task lists or searches, and trial ownership cannot be transferred.
Polling preserves the runner's saved completion outcome, including cancellation, and reports the underlying task status separately.
A poll can recover a missing export without replacing an existing result.

Individual skill reads and markdown downloads serve the run's pinned candidate.
Trial sandboxes can use stub skill bundles, which fetch each skill through those reads.
Full-content bundles are rejected because they cannot apply the run's private candidate; ZIP exports remain unavailable to scoped trial credentials.

The [live comparison plan and script](../../products/signals/eval/experiments/2026-09-long-running-agent-evals/PLAN.md#live-trial-operator-script) describe launch inputs, stored results, and supported scout capabilities.
Keep downloaded prompts, memory, reports, and transcripts outside version control.

### Rubric mock for comparison development

The [mock rubric fixture](../../products/signals/backend/scout_harness/mock_scout_rubric.json) matches the read response in [the scout rubric editor PR](https://github.com/PostHog/posthog/pull/106580), checked at `d7c6c3742ba`.
It contains the six default criteria, `revision: 0` (unsaved defaults), and `generation: null`.
These are mock inputs for developing scoring and reports, not a saved or reviewed rubric for the selected scout.

Print a mock response for a scout:

```sh
python products/signals/backend/scout_harness/trial_rubrics.py \
  --config-id 00000000-0000-4000-8000-000000000001 \
  --skill-name signals-scout-example
```

The [rubric reader](../../products/signals/backend/scout_harness/trial_rubrics.py) defines `ScoutRubricReader` and `MockScoutRubricReader` for comparison code.
`read(config_id=..., skill_name=...)` returns a fresh document with the supplied scout identity and the API's unchanged field names.
The reader does not write scout configuration, generate criteria, or score runs.

When the real rubric API is available, replace the mock reader with a reader for `GET /api/projects/{team_id}/signals/scout/rubrics/{config_id}/`, preserving that response shape.
Keep the editor, storage, and generation in the rubric feature; do not add a second implementation to comparisons.
The real reader must propagate missing-rubric and access errors rather than falling back to mock criteria.

Scoring saves the returned rubric document, enabled criteria and revision with the comparison before judging, so every variant uses the same rubric.
The evaluation records `rubric_source: mock` separately from the API document and labels its report as a mock rubric evaluation.
Only enabled `criteria` are judged; `generation.suggestions` remain drafts.

### Saved scoring and reports

Scoring is an explicit action after all selected runs reach a known terminal state and incurs additional model charges.
The request names a baseline and variant groups, with at most 20 distinct launches from the same scout, operator and saved starting context.
Runs within a variant must use the same instructions, note, model, runtime, reasoning effort and service tier.
The server freezes the rubric, bounded evidence, judge model and prompt version before dispatching the judge.
Evidence includes instructions, starting history, captured reports, memory changes, summaries and available tool calls and results.
Missing or truncated evidence is recorded as a limitation; private thoughts and reasoning are excluded from the extracted trace.

The judge receives criteria and evidence without variant labels or scout model settings.
It returns one verdict per criterion: pass, fail, unknown or not applicable.
Pass, fail and not applicable require source references and exact quotations from the saved evidence.
Unverifiable citations become unknown, and quoting an instruction alone cannot prove it was followed.
Missing evidence is unknown; not applicable means the criterion does not apply to that run.
The judge assesses the saved text and does not independently verify external sources or measure recall.

A run's score is `pass / (pass + fail)`, or null when it has no decisive verdicts.
A variant's score is the equal mean of its non-null run scores.
Coverage is `(pass + fail) / (pass + fail + unknown)`; not applicable is excluded from both score and coverage denominators.
Execution exclusions and judge errors have no quality score and are counted separately.
Reports retain each run's verdicts, reasons, quotations and evidence limitations alongside aggregate counts.
Baseline differences are withheld unless all selected runs were judged with complete, comparable verdicts.
The differences describe these runs; they do not establish statistical significance or a reliable winner.
Shared starting history does not freeze the live project data read during each run.

Scoring uses `POST /api/projects/{team_id}/signals/scout/configs/{config_id}/trial_evaluation/`.
Read the saved outcome with `GET /api/projects/{team_id}/signals/scout/configs/{config_id}/trial_evaluation_result/?evaluation_id=...`.
Reuse an evaluation ID only for the same request; a different request with that ID is rejected.
Retries reuse saved work and do not repeat an attempted judge call automatically.
Polling reads the saved status or report without starting model calls.
Every read remains restricted to the operator's current project and skill access.

### Internal comparison UI

Staff members in project 2 can open **Scouts > Compare scouts** to choose a scout, add prompt/model/effort variants, and set the number of runs per variant.
The page submits at most 20 runs per comparison and shows deployment or scout compatibility blockers before launch.
The first accepted launch saves the shared starting history; remaining launches reuse it with their own private writable state.
Keep the page open until all submissions are confirmed. Accepted runs continue on the server after the page closes.

The page shows the operator's recent private runs, supports stopping active runs, and exports their captured reports, memory changes, and available usage as JSON.
Once its runs finish, select a comparison and choose **Score comparison** to use the mock rubric.
The report shows variant and run scores, coverage, criterion verdicts, supporting quotations and separate execution or judging errors, with a JSON export.
Reloading the page restores saved scoring status without starting another evaluation.
If a report contains judge errors, **New scoring attempt** prepares a new evaluation of the same scout runs and keeps the old report available.
Choose **Score comparison** to start that attempt; it may charge for all runs again.
Browser storage keeps only scout, comparison, variant, baseline and launch IDs, scoped to the project and operator; prompts, labels, evidence and reports stay out of browser storage.
Unsubmitted prompt edits are lost on reload; start a new comparison instead of reconstructing an uncertain request.
The setup, history and scoring endpoints enforce the staff/project restriction on the server, in addition to existing scout permissions.
Shared instructions guide investigations but do not enforce date or file access limits.

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
