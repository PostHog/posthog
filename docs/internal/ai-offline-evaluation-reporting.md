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

Scoring freezes the full rubric document, enabled criteria, saved revision and governing references before judging, so every variant uses the same requirements.
The report and JSON export retain the frozen references and their generation identity for inspection.
The [mock fixture reader](../../products/signals/backend/scout_harness/trial_rubrics.py) remains available for offline development.
Existing mock snapshots and reports remain readable, and exact-ID retries reuse their saved request; a new evaluation ID requires the saved rubric.

### Saved scoring and reports

Scoring is an explicit action after all selected runs reach a known terminal state and incurs additional model charges.
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
Versions 6 and 7 distinguish missing source IDs, blank or mismatched quotations, instruction-only evidence and missing citations in the normalized reason. These reasons contain no rejected quotations or raw model output.
New evaluations record judge version 7. It uses the same prompt as version 6: count claims must follow the query and observed identifiers, so an aggregate alias or a distinct count of placeholder identifiers does not establish real users or entities. Citations must use the envelope's source IDs and exact text from the corresponding source.
Version 7 allows at most 16,000 completion tokens per run; versions 1 through 6 retain their 8,000-token limit. A version 7 response that reaches the limit produces a judge error with guidance to review the rubric size before starting a new evaluation. It retains token usage but no partial verdicts and makes no automatic retry. The 64,000-character verdict-document limit is unchanged.
Pending versions 1 through 6 retain their original prompts, evidence envelopes, citation normalization and request limits. Versions 5 and 6 continue to use their separate, fixed reference context; previously saved snapshots and reports remain unchanged.
Missing evidence is unknown; not applicable means the criterion does not apply to that run.
The judge assesses the saved text and does not independently verify external sources or measure recall.

A run's score is `pass / (pass + fail)`, or null when it has no decisive verdicts.
A variant's score is the equal mean of its non-null run scores.
Coverage is `(pass + fail) / (pass + fail + unknown)`; not applicable is excluded from both score and coverage denominators.
Execution exclusions and judge errors have no quality score and are counted separately.
A scout runner failure remains an execution exclusion even if its sandbox task completed; the saved trial outcome records the runner failure.
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
Once its runs finish, select a comparison and choose **Score comparison** to use the reviewed saved rubric.
The report shows variant and run scores, coverage, criterion verdicts, supporting quotations and separate execution or judging errors, with a JSON export.
Reloading the page restores saved scoring status without starting another evaluation.
After scoring completes or fails, **New scoring attempt** prepares a new evaluation of the same scout runs using the current saved rubric and keeps the old report available.
Choose **Score comparison** to start that attempt; it may charge for all runs again.
Browser storage keeps only scout, comparison, variant, baseline and launch IDs, scoped to the project and operator; prompts, labels, evidence and reports stay out of browser storage.
Unsubmitted prompt edits are lost on reload; start a new comparison instead of reconstructing an uncertain request.
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
