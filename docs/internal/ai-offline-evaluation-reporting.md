# Offline evaluation result reporting

The evaluation harness in `products/posthog_ai/eval_harness/` reports public-suite scorer results to Braintrust.
Suites under `products/posthog_ai/evals/` and the product-owned `products/*/evals/` trees also publish those results to PostHog's offline experiment API when a publishing credential is configured.
The Signals pytest suites reuse the same publisher for their completed results.
Agent and judge trace capture remains available.
Reporting does not run the agent or scorers again.
Use `hogli evals` to run PostHog AI 2.0 suites. See the [eval harness guide](../../products/posthog_ai/eval_harness/README.md) for suite discovery and execution.

## Capture settings

`no_send_logs` controls Braintrust uploads and, by default, PostHog result uploads.
`SandboxedPublicEval` sets `no_send_logs=False` and uploads to Braintrust, plus PostHog when the suite has offline publishing configured.
`SandboxedPrivateEval` sets `no_send_logs=True` and uploads to neither service by default; local logs are still written.
Set `send_to_posthog=True` alongside `offline_suite` to publish results to PostHog while keeping Braintrust uploads disabled.
Set `send_to_posthog=False` to disable PostHog result uploads independently. The same options apply to one-shot suites.

Suites that disable Braintrust uploads declare `NO_SEND_LOGS = True` at module level and pass `no_send_logs=NO_SEND_LOGS` to their runner.
Discovery uses this declaration to validate credentials before starting infrastructure; the enrollment test checks that it matches the runner.
`BRAINTRUST_API_KEY` is required for reporting only when at least one selected suite enables Braintrust uploads.
PostHog-only suites still use the Braintrust library locally, without authenticating to its experiment service.
Scorer model credentials remain separate: using Braintrust's model proxy still needs its credential, while other providers use their own keys.

Offline API uploads run through the Python SDK independently of `TEST` and `OPT_OUT_CAPTURE`.
The shared trace client retains its existing `TEST` and `OPT_OUT_CAPTURE` guards for `$ai_generation`, `$ai_span`, and `$ai_trace` events.

## Result contents and scope

Published results include experiment, case, and scorer details, with input, output, and expected values when available.
Run metadata includes `agent_model`, `trials`, `git_sha`, `git_dirty`, and for sandboxed runs `agent_runtime`, `skill_delivery`, and `reasoning_effort`.

Each trial has a unique ID in engine metadata. Local logs and summaries use that ID, so repeated trials retain separate output and scores.
The harness shortens long case names in filenames to stay within 255 bytes. It keeps the complete trial ID and file extension.
Scorer traces and agent trace roots use the same ID to match each result to its own execution.
Case names stay the same across trials.
For a repeatable smoke comparison, use the [Claude and Codex command pair](../../products/posthog_ai/eval_harness/README.md#claude-and-codex-smoke-comparison).
Both commands select the same MCP case and record the model, runtime, delivery mode, and checkout.
Compare completed coverage and infrastructure errors alongside named scores and duration.
Add `--compare` to one selected sandboxed run to execute both default models and save a combined local comparison.
Repeated `--compare-model RUNTIME:MODEL` options select explicit models. The comparison checks both configurations
before running agents, retains each model's results, and reports case or scorer selection differences.
This local comparison does not change the suite's upload or capture settings.
Trial metadata and local summaries also record phase durations in seconds.
The scoring phase includes time waiting for the experiment results, rather than scorer execution alone.
A failed final metadata upload produces a warning and keeps the completed results available locally.
A scorer failure marks the case as an error. Statistics still include scores from other successful scorers.

## Configured offline experiment suites

Shared-harness suites are enrolled in the offline experiment publisher, including both sandboxed and one-shot suites, except for `logs/eval_agent_observability::eval_agent_observability`, which currently reports only to Braintrust.
The experiment-skill, Feature Flags, Dashboards, turn-suggestion and Business Knowledge retrieval suites retain `no_send_logs=True` and explicitly set `send_to_posthog=True`, publishing results only to PostHog.
Public suites retain their Braintrust uploads during enrollment. Braintrust also remains the execution engine for every shared-harness suite, including those whose results publish only to PostHog.
After scoring, the harness prepares the completed results in memory and queues delivery through the Python SDK's `AsyncOfflineEvaluations` client. It does not execute another agent run or judge call.
Without an explicit `send_to_posthog` override, `no_send_logs=True` suppresses this upload too.

The [PostHog AI catalog](../../products/posthog_ai/evals/offline_config.py) and each product's `evals/offline_config.py` pin destination project `2`, scorer kinds, immutable version UUIDs, and component tags.
Suites select their own metrics from the catalog; sandboxed suites also include the harness-provided `exit_code_zero` metric.
The SQL suite retains its seven existing scorer versions.
The discovery-wide enrollment test checks every enrolled suite's publishing flag, stable key, scorer coverage, pinned UUIDs and ownership tags without executing agents or judges. It also checks that the Logs agent-observability suite retains its Braintrust-only reporting configuration.
Provide the API key through the environment before running the suite:

| Variable                       | Purpose                                                                                                                                                                                                                                  |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POSTHOG_OFFLINE_EVAL_API_KEY` | Personal API key with `offline_evaluation_ingestion:write` and `evaluation:write` to upload and tag results. Ingestion-only personal or project secret keys can upload without tags. A public project token cannot authenticate uploads. |
| `POSTHOG_OFFLINE_EVAL_HOST`    | App origin; defaults to `https://us.posthog.com`.                                                                                                                                                                                        |

The publisher normalizes the cloud ingestion hosts (`us.i.posthog.com`, `eu.i.posthog.com`) and the legacy `app.posthog.com` host to their app origins.
Uploads, result links, and trace-destination checks use that same origin.

Experiments submitted with a personal API key are attributed to that user. Project secret API key submissions
have no author. Attribution is recorded on the first accepted submission and stays unchanged on retries.
The offline evaluations overview shows the author and supports filtering experiments and score trends by author,
including experiments with no author. Choose "Any author" to clear the filter.
Scorer history includes the same author control, so filters carried from the overview remain visible and can be cleared.
API requests cannot combine `created_by` with `created_by_is_null=true`.
Each scorer chart displays the loaded versions with results in the selected date range and filters as separate series,
while the summary defaults to the latest matching version. The version arrows change only the summary.
Opening a scorer's history preserves the author and date filters and selects the version shown in the summary.
The scorer list shows each scorer's creator and last editor, and can be filtered by creator.
By default, scorers are sorted by last updated, newest first.
Creating and editing scorers stays under Evaluations → Scorers, with a detail heading and a back link to the list.
Successful creation and edits return to the scorer list; failed saves keep the form open with your changes.

Online evals, offline experiments, datasets, and scorers have independent setup states. The Evaluations tabs
stay available when no online evaluations exist, and the offline Experiments and Datasets tabs remain visible
during dataset setup. The experiments setup links to the [offline evals guide](https://posthog.com/docs/ai-evals/offline-evals).
The offline setup preview compares prompt and model combinations with multiple scorers. Scorer setup shows how
numeric, boolean, and categorical definitions are shared by offline experiments and
[manual trace reviews](https://posthog.com/docs/ai-observability/trace-reviews). Archived scorers remain accessible
from the setup screen; filtered lists keep their filters and results table.
Dataset setup appears only when there are no active or archived datasets, so projects with only archived
datasets can still browse and restore them from the list.

Scorers have an optional **Short name** (up to 40 characters) for experiment table headers and other compact views.
These views use the full name when the short name is blank. Editing or clearing a short name updates existing
experiment displays without creating a scorer version or changing scoring rules. Versions appear in a separate badge.

The SQL suite uses these existing scorers:

| Metric name                          | Scorer kind                      |
| ------------------------------------ | -------------------------------- |
| `exit_code_zero`                     | Boolean                          |
| `no_persistent_insight_save`         | Boolean                          |
| `execute_sql_called`                 | Boolean                          |
| `answer_tool_not_typed_query`        | Boolean                          |
| `querying_posthog_data_skill_loaded` | Boolean                          |
| `sql_schema_alignment`               | Numeric, minimum 0 and maximum 1 |
| `sql_result_message_alignment`       | Numeric, minimum 0 and maximum 1 |

The harness loads the repo-root `.env` automatically; shell values take precedence.
For CI, store the key as the `POSTHOG_OFFLINE_EVAL_API_KEY` [organization Actions secret](https://github.com/organizations/PostHog/settings/secrets/actions), grant access to the selected repository `PostHog/posthog`, and expose it to the eval step under the same environment variable name.
No project ID or scorer mapping environment variables are required.

```bash
export POSTHOG_OFFLINE_EVAL_API_KEY='your-secret-key'
hogli evals sql/eval_sql::eval_sql
```

Without an API key, each enrolled suite reports that offline uploads are disabled.
Keys containing whitespace are rejected before evaluation starts; remove any spaces, tabs, or pasted trailing newlines.
Invalid configuration produces a warning and skips this destination; Braintrust and local reporting continue.
An upload failure also warns without changing the evaluation's score gate.
The final summary shows a PostHog results link only after a successful offline upload; otherwise it shows the upload status.

### Testing uploads against local PostHog

Set `POSTHOG_OFFLINE_EVAL_HOST=http://localhost:8010` and use a personal API key created in that local instance.
HTTP is accepted only for `localhost`, `127.0.0.1`, and `::1`; other hosts require HTTPS.
The eval harness's temporary test database is separate from the development instance receiving uploads.

The suite catalogs contain production project and scorer-version IDs. To use local scorers without editing those catalogs, set
`POSTHOG_OFFLINE_EVAL_LOCAL_CONFIG=.env.local.offline-evals.json` in `.env.local`. The JSON file selects a local project and maps
each catalog scorer-version UUID to a version created in that local project:

```json
{
  "project_id": 2,
  "scorer_versions": {
    "00000000-0000-4000-8000-000000000002": "00000000-0000-4000-8000-000000000003"
  }
}
```

The UUIDs above are placeholders. Create the needed scorers under **Evaluations → Scorers**, matching each catalog metric's kind,
and use their immutable version IDs. Include every scorer used by the selected suites; a single file can cover multiple suites.
The file is gitignored by the `.env*` rule. Local configuration is accepted only with a loopback upload host.
An unreadable, invalid, or incomplete file disables the upload with an error; it never falls back to the production catalog.

Run through `hogli evals` to load `.env.local`; existing shell variables take precedence.
For PostHog-only testing, select suites declaring `NO_SEND_LOGS = True`, such as Feature Flags or Dashboards.
Set `OPT_OUT_CAPTURE=1` to suppress ordinary SDK/trace capture while retaining explicit offline-result uploads.

### Scorer and experiment tags

Score definitions and experiment runs use the same team and component tags:

| Suites               | Tags                                                                                        |
| -------------------- | ------------------------------------------------------------------------------------------- |
| PostHog AI           | `team:surfaces`, `component:posthog-ai/<domain>` (for example `sql` or `product-analytics`) |
| Slack app            | `team:surfaces`, `component:slack-app/<area>` (for example `followup-classifier`)           |
| Conversations        | `team:conversations`, `component:conversations`                                             |
| Business Knowledge   | `team:conversations`, `component:business-knowledge`                                        |
| Data Catalog         | `team:data-modeling`, `component:data-catalog`                                              |
| Notebooks            | `team:data-tools`, `component:notebooks`                                                    |
| Feature Flags        | `team:feature-flags`, `component:feature-flags`                                             |
| Dashboards           | `team:product-analytics`, `component:dashboards`                                            |
| Signals grouping     | `team:self-driving`, `component:signals/grouping`                                           |
| Signals scout safety | `team:self-driving`, `component:signals/scout-safety`                                       |

`OfflineEvalSuite.tags` supplies the experiment tags. Delivery records the successful upload and results link once the experiment has completed, then calls the publisher's `tag()` method to update tags through the Python SDK's `experiment.set_tags(...)`. Tagging has its own five-second deadline outside the upload deadline. Tags are mutable metadata, separate from the immutable creation declaration and scorer versions.

To upload **and tag** experiments, `POSTHOG_OFFLINE_EVAL_API_KEY` must be a personal API key with both `offline_evaluation_ingestion:write` and `evaluation:write`. An ingestion-only personal or project secret key can still upload results, but the tag update will warn. Tagging failures, timeouts, and shutdown interruptions retain the successful upload status and results link and do not change the evaluation score gate.

Each prepared experiment's tag update is attempted once per publisher, including when delivery pauses and resumes. A failed or interrupted replacement is not repeated automatically, because it may already have succeeded or someone may have edited the tags afterward. Inspect the experiment's tags before manually retrying a replacement.

### Additional one-shot suites

Run these through the same harness and publishing lifecycle:

```bash
hogli evals turn_suggestions/eval_turn_suggestions::eval_turn_suggestions
hogli evals business_knowledge/eval_retrieval::eval_retrieval
hogli evals conversations/eval_support_reply::eval_support_reply
```

Turn suggestions reuse the labeled benchmark cases and the configured System One judge, once per case.
`TURN_SUGGESTIONS_EVAL_THRESHOLD` overrides the production show threshold for the run; it must be between 0 and 1.
Case metadata records the threshold and requested judge model, and outputs retain the selected offer, probability, outcome and duration.
An accepted optional offer counts as correct; an unavailable judgment reports an error.
The existing `turn_suggestions_benchmark` command remains available for multi-endpoint comparisons and threshold sweeps; those modes are not part of this suite.

Business Knowledge retrieval reuses the labeled `retrieval_eval.yaml` corpus and queries.
Each case seeds an isolated team, searches the corpus and cleans up the team.
Its boolean score checks the existing found/not-found expectation, including queries expected to return no results.
It does not score source relevance or replace the ordinary retrieval unit tests.

Support reply retains its existing behavior: mocked by default, or live when `SUPPORT_REPLY_EVAL_LIVE=1`.
Both case metadata and output identify the mode so runs can be compared within the same mode.

These suites use the existing one-shot infrastructure and credential prerequisites described in the harness guide.
The turn-suggestion judge additionally needs its existing System One configuration; selecting the suite does not configure that service.
MCP saved-report grading, semantic-layer canary commands and ReviewHog campaigns retain their separate workflows and are not enrolled by these wrappers.

### CI configuration

CI jobs running enrolled suites need `POSTHOG_OFFLINE_EVAL_API_KEY` and `BRAINTRUST_API_KEY` in the environment.
Map the dedicated `ANTHROPIC_OFFLINE_EVALS_API_KEY` and `OPENAI_OFFLINE_EVALS_API_KEY` Actions secrets to `LLM_GATEWAY_ANTHROPIC_API_KEY` and `OPENAI_API_KEY` for the harness and judges.
Publishing failures remain warnings, so check the final harness upload status even when a CI job is green.
The harness sets the SDK's `run_source` to `ci` when `CI` is set, including manual Actions runs, and to `local` otherwise.

### Published results

Each case and trial becomes a separate item, with one result per configured scorer.
Boolean scores convert `0` and `1` to `false` and `true`; numeric scores retain their values.
Both `false` and numeric zero have status `ok`: this status means scoring produced a value, not that the agent passed.
A `None` score becomes `skipped`; a task error or missing scorer result becomes `error`, with no score value.
LLM judge exceptions publish an `error` outcome with code `judge_error`; the existing zero fallback remains in Braintrust and local aggregates.
A failed scorer does not replace successful results from other scorers on the same case.
Scorer metadata and `reason` or `rationale` explanations are retained for each trial, including skip reasons and judge errors.
The scorer recorder observes return values and exceptions only when a suite has valid offline publishing configuration and allows uploads. Other runs pass scorers directly to Braintrust.
Braintrust still owns scorer execution, return-value validation, and numeric aggregation.
Application and evaluator trace links are included when capture is enabled and the trace and offline destinations match.
Application and dataset revisions use the commit captured at run start.

Items include available input, output, expected output, and case metadata.
The publisher excludes `raw_log` from the new API payload; the existing local logs and Braintrust output retain it.
The SDK validates optional fields and the combined payload as fields are added. An invalid or oversized field is omitted as a whole, with its name recorded in `metadata.omitted_fields`.
Item payloads prioritize input, output, expected output, then metadata. Output fields are not pruned individually, and accepted fields are not removed to make room for omission diagnostics.
Invalid optional case keys, dataset references, or trace identifiers are omitted individually, preserving the other cases and scores in the prepared upload.

The publisher retains the prepared experiment, items, scorer versions, and result payloads in memory until delivery finishes.
The SDK owns request validation, batching, acknowledgements, and retries. Requests use a 5-second timeout and up to two retries with the same experiment and item identities, subject to the overall upload deadline.
This leaves time for create, one upload batch, and completion to each retry timed-out requests within the 60-second upload budget. Larger uploads and server-requested retry delays still share that budget; retries are not guaranteed to finish before it expires.
Failure reports retain sanitized error codes and field paths, persistence state, retry guidance, and acknowledged batch/item/result counts without including raw responses or result payloads.
Local case exports finish before delivery is queued. Up to two uploads run concurrently, with at most 32 queued or active uploads and a 60-second deadline per active upload.
After suites finish, the harness pauses unfinished uploads before synchronous infrastructure teardown, then retries the same prepared objects with fresh request and upload deadlines.
These retries retain the experiment, item, and scorer version identities, including after partial acceptance or a lost completion response.
The harness waits up to the full upload deadline (60 seconds by default) for remaining uploads after teardown, including time waiting for a delivery slot.
After an API error following successful experiment creation, the publisher makes a best-effort attempt to mark the experiment failed, limited to 5 seconds, and retains the original upload error. Accepted results remain available on failed experiments.
Pausing or cancelling delivery does not mark the experiment failed, so teardown pauses can resume the same experiment. Timeouts, interruptions, and failed cleanup can leave an experiment in the uploading state.
Timeout, cancellation, a full queue, or a rejected request produces a warning without changing the score gate.
Failed or interrupted uploads are not saved for later retry. To try publishing again, correct the configuration or connectivity problem and rerun the suite.
Existing local logs, enabled case exports, and Braintrust results remain available.

### Enrolling other suites and richer results

Both `SandboxedEval` and `OneShotEval` accept `offline_suite=OfflineEvalSuite(...)`.
Each suite declares its destination `project_id`, selects at least one metric in `scorer_kinds`, and pins the corresponding immutable version UUIDs in `scorer_versions`.
These fields belong to `OfflineEvalSuite` in code. Scorer version UUIDs must be distinct for the suite's enrolled metrics.
Catalog helpers add `exit_code_zero` for sandboxed suites. One-shot suites pass `suite_kind=SUITE_KIND` to enroll only their declared metrics.
Numeric scores can use the domain of their configured scorer version. The API validates bounds and steps; the harness does not restrict every numeric metric to `[0, 1]`.

`OfflineEvalSuite.experiment_options` accepts the SDK's `ExperimentOptions` for external dataset identifiers, `prompt_version`, model/application versions, and `run_source`.
The harness owns the experiment ID, start time, suite key, and expected counts.
For external datasets, case metadata can supply `dataset_item_identifier` and `dataset_item_version_identifier`.
The harness publisher does not support hosted datasets. A non-null `dataset_revision_id` stops preparation with a local error before any upload request.

Ordinary scorers continue returning numeric `Score` values. A scorer can additionally return a typed `ScorerResult` through `Score.result` to publish categorical values or `not_applicable`, explicit errors, reasoning, metadata, timestamps, and evaluator trace references:

```python
from products.posthog_ai.eval_harness.engines.types import ScorerResult
from products.posthog_ai.eval_harness.scorers.contract import Score

result = Score(
    name="answer_category",
    score=None,
    result=ScorerResult(status="ok", value=["correct"], reasoning="The answer matches the reference."),
)
```

The numeric `score` still controls existing Braintrust and local aggregates; `result` describes the offline outcome. Configure this example's scorer kind as `categorical`.
Scorer provisioning stays separate from uploading results, so publishing requires only the ingestion scope and does not create or modify scorer definitions.

## Signals pytest suites

The suites in `products/signals/eval/` keep their pytest runner and mocked infrastructure.
They publish completed metrics through `OfflineEvalPublisher` without running the pipeline or judges again.
Run them from the repository root:

```bash
pytest products/signals/eval/eval_grouping_e2e.py products/signals/eval/eval_scout_safety.py
```

The grouping suite has 111 input signals across 48 fixture groups; scout safety has 7 cases.
Each suite execution publishes one experiment: `signals/grouping-e2e` or `signals/scout-safety`.
Grouping records separate items for pipeline stages, generated reports, and aggregate statistics, so uploaded item counts exceed the input signal count.
Scout safety records one item per case and one aggregate item.
Use `--limit N` for a subset; the run metadata records the limit and checkout revision.

Both suites target project `2` and pin immutable scorer version UUIDs in
[`offline_config.py`](../../products/signals/eval/offline_config.py).
There are 16 grouping scorers and 3 scout safety scorers, reused across inputs.
Classification checks at different stages have separate scorers.
Per-report `group_recall` and aggregate `mean_group_recall` also stay separate.
Metrics that do not apply to an item's stage publish `not_applicable`.
Numeric definitions allow ARI in `[-1, 1]` and query cosine distance in `[0, 2]`.

Set `POSTHOG_OFFLINE_EVAL_API_KEY` with `offline_evaluation_ingestion:write` and optionally
`POSTHOG_OFFLINE_EVAL_HOST`, as for the SQL suite.
Missing or invalid configuration disables offline uploads with a message; upload failures also report a message without changing the eval outcome.
Successful uploads print the experiment URL.
Scout results upload before the existing assertion against unsafe payload leaks.
Each execution has a fresh experiment ID, so repeated runs do not overwrite one another.

`--no-capture` suppresses result uploads and trace capture.
`POSTHOG_PROJECT_API_KEY` and `POSTHOG_HOST` remain the separate trace-capture settings.
Runs appear in the offline experiments UI.

## Postgres experiment ingestion

The project API accepts offline experiment results behind the `ai-observability-offline-evaluations` feature flag.
The configured public suites call this API to publish completed scorer results.

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

## Resource tags

Datasets, stable scorer definitions, and offline experiments use the shared project tag vocabulary.
Tags belong to the resource, not to dataset revisions or scorer versions, and do not propagate between linked resources.
Their list and detail responses include `tags`. Dataset and scorer creation and updates accept a `tags` array.
Use `PATCH /api/projects/{project_id}/ai_observability/offline_experiments/{id}/` with `{"tags": ["quality", "production"]}` to replace experiment tags; it requires evaluation editor access and `evaluation:write` for personal API keys. Ingestion credentials cannot edit tags.
Omitting `tags` preserves existing assignments, including an empty experiment PATCH body; sending `[]` clears them. Names are trimmed and lowercased, with up to 100 tags of at most 255 characters each after normalization.
Saving unchanged scorer tags preserves the update timestamp and does not emit a scorer update event.
Removing the last assignment of a tag removes it from the shared project tag vocabulary.

All three list APIs accept `tags` as a JSON-encoded array of up to 20 names and `tag_match=any` (OR, the default) or `tag_match=all` (AND).
For example, `?tags=%5B%22quality%22%2C%22production%22%5D&tag_match=all` finds resources with both tags, including resources with additional tags.
Filters apply before pagination; an empty array disables tag filtering. MCP list tools expose the same parameters, and update tools can replace tags.
Assignments use the shared generic tagged-item relation. List queries use correlated existence checks and batch tag loading, so multiple matching tags do not duplicate rows or add a query per resource.
Each save inserts normalized tag names in sorted order to prevent deadlocks when concurrent workers create the same tags.

The three tables have a Tags column before the timestamp columns, showing up to two tags with remaining tags in an overflow popover and a control to edit assignments.
Tag filters are included in the URL and remembered separately per resource type, project, and user in browser storage. Changing tags or their match mode resets table pagination.
Explicit URL filters take precedence over remembered filters, including `tags=[]` to clear them.
On the offline overview, the top-level tag selector filters both the recent experiments table and score trend charts.
Scorer history supports the same tag filters through its UI, API, and MCP tool, including comparison periods. Its tables show experiment tags without editing controls.
Experiment views share remembered tag filters, while explicit URL filters take precedence.
Opening scorer history from an experiment clears remembered tag filters so they cannot hide that experiment.

## Postgres experiment reads

Read endpoints use the same feature flag as ingestion.
The offline UI uses these APIs. The configured SQL pilot and Signals suites publish results here.

The following GET paths are relative to `/api/projects/{project_id}/ai_observability/`:

| Path                                                               | Response                                                                             |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| `offline_experiments/`                                             | Experiments, run context, lifecycle state, and counts.                               |
| `offline_experiments/{experiment_id}/`                             | One experiment, regardless of list date filters.                                     |
| `offline_experiments/{experiment_id}/items/`                       | Item metadata, payload availability, and optionally selected scorer-version results. |
| `offline_experiments/{experiment_id}/result_cells/`                | Result cells for fixed item and scorer-version identities.                           |
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

For a matrix with more than 20 scorer versions, fetch an item page once, then call `result_cells/` with its fixed `item_ids` and batches of `scorer_version_ids`.
Both lists are required; requests allow up to 50 distinct item UUIDs and 20 distinct scorer-version UUIDs.
The response includes scorer metadata and existing result cells, without payloads.
An absent cell is a missing result only after its batch resolves successfully.
Items must belong to the requested experiment and versions must be visible to the caller in the same environment.
Version selection preserves unscored items, which have missing cells.
Use the paginated item results endpoint to inspect additional versions; it includes full scorer metadata and configuration on each result.
List and summary endpoints do not load input/output or reasoning payloads.

## Scorer versions and summaries

Discover immutable versions through `GET /api/projects/{project_id}/llm_analytics/score_definitions/{definition_id}/versions/`.
Retrieve a specific version at the same path followed by `{version_id}/`.
These operations use the existing scorer read permissions and include historical versions without recent results.
Archived scorers remain addressable, including their versions and offline history, while default scorer selection excludes them.
Creating another version with an unchanged configuration remains supported.
Scorer configurations can optionally define which values pass:

- Boolean `true_is_failure: false` makes true pass; `true_is_failure: true` makes false pass. Omitted or null polarity defaults to true passing.
- Categorical `passing_rule` contains `categories`, a list of configured category keys. Every selected category must be included for a result to pass. Single-select rules require at least one passing category; a multi-select rule may have an empty list, making all accepted results fail. Offline results still require a nonempty selection. Omit the rule or set it to null for neutral scores.
- Numeric `passing_rule` contains `operator: "gte"` (at or above) or `operator: "lte"` (at or below), and a finite `threshold` within the scorer's configured bounds. Omit the rule or set it to null for neutral scores. Thresholds need not align with the input step.

Passing rules classify accepted scores; a failing score still has execution status `ok`.
Each immutable version keeps its own polarity and rule. Changing a scorer creates a new configuration version without reinterpreting historical offline results or saved manual review snapshots.
Numeric scorers without a passing rule remain neutral. The editor always offers a passing value for boolean scorers and persists the default polarity when saving a configuration.

Experiment summaries and scorer history use the same aggregation rules over all matching results, independently of item pagination or payload availability.
Different scorer versions remain separate, even when their configurations match.

| Kind        | Summary                                                                                |
| ----------- | -------------------------------------------------------------------------------------- |
| Numeric     | Mean of successful values and the successful sample count.                             |
| Boolean     | True and false counts, with the true rate among successful results.                    |
| Categorical | Counts and rates per key from the pinned version, including keys with no observations. |

Boolean scorers and numeric or categorical scorers with a passing rule also return `pass_count`, `fail_count`, and `pass_rate`.
The rate divides passing results by successful results, excluding errors, skipped, not-applicable, and missing results.
Numeric pass counts evaluate each result against the threshold, independently of the mean.
Without successful results, boolean scorers and numeric or categorical scorers with a passing rule return zero pass/fail counts and a null rate. Numeric and categorical scorers without a rule return null for all three fields.

Multiple-selection category rates divide by the successful result count and can add up to more than 100%.
Error, skipped, and not-applicable outcomes are counted separately and excluded from value summaries.
No successful results produces a null mean or rate.
Missing results among observed items are reported separately and do not indicate how many entirely absent items were intended.
Each repeated trial contributes one item; summaries also expose case and trial coverage without applying per-case weighting.
Numeric increases do not imply better quality unless that meaning is established by the pinned scorer configuration. Boolean true passes by default unless the pinned version sets `true_is_failure: true`.

## Reading payload availability

### MCP access

The `llma-offline-experiment-*` and `llma-offline-scorer-history` MCP tools expose
these reads and the create/upload/complete/fail lifecycle behind the same
`ai-observability-offline-evaluations` flag. Lifecycle tools record externally
computed results; they do not execute evaluators. Scorer configuration remains on
the existing `llma-score-definition-*` tools, with `version-list` and `version-get`
for immutable version discovery. Version tools use the existing scorer permissions.

Read tools remain available to SQL-first consumers because their curated responses
preserve scorer access controls, immutable configs, and full-run aggregation rules.
Pagination preserves `count`, `next_cursor`, and shared `scorer_versions`. MCP list
tools default to 20 rows. Metadata reads require `evaluation:read`; score reads and
scorer filters also require `llm_analytics:read`. Ingestion uses
`offline_evaluation_ingestion:write` and does not confer read access.

The item/result `payload-get` tools use generated handlers and return the full stored
JSON object in `data`, with the API's availability metadata. Unavailable payloads
return `data: null`. These reads are not paginated; agents should inspect summaries
and item metadata first, then fetch payloads only for relevant cases. Large payloads
can consume substantial context or be truncated by the client. Payloads and other
user-authored records are wrapped as untrusted reference data.

The published `analyzing-offline-evaluations` skill describes comparable cohorts,
coverage-aware interpretation, case drill-down, and result publication. The legacy
event-backed experiment-items endpoint is not exposed by these tools.

### Availability states

Items and results expose their own `payload_state` and `payload_expires_at`.
Payload detail responses include `available` and `data`, preserving omitted properties, empty objects, and explicit JSON null values.
`not_provided` means the caller omitted the payload; `expired` means it was removed while its owner was retained.
An unavailable payload has null `data`, while durable identities, results, and summaries remain readable.

A deadline alone does not mean a cleanup worker has removed the payload.
Automatic deletion remains separate work.
Expired input/output is not reconstructed from linked datasets or traces, and missing links do not prevent experiment reads.
Opening those resources requires their own permissions.

## Inspecting offline results

Open **Evaluations → Offline evals** to see the newest experiments and chosen score trends.
When offline evaluations are enabled, **Experiments** is selected by default. **Datasets** opens the list on the same page
with `tab=datasets` in the query string. MCP-generated dataset-list links retain this tab selector.
Existing `/ai-evals/datasets` and `/llm-analytics/datasets`
links redirect there, preserving filters and pagination. Dataset creation and detail pages live at
`/ai-evals/evaluations/offline/datasets/:id`, within the Offline evals navigation. Both legacy dataset
detail routes redirect there, preserving item deep links, revisions, tabs, filters, and hashes.
The Evaluations heading and navigation stay in place on dataset creation and detail pages. Dataset items appear
directly in the detail view; **Details** opens the dataset metadata without replacing the items table.
The back arrow beside the dataset name returns to the list and preserves its filters, including after creating a dataset.
Creation and editing actions appear below the dataset form. Switching from Experiments to Datasets clears
experiment search and filters and restores the saved dataset tag selection.
Projects with Datasets enabled but without offline evaluations open **Datasets** automatically,
including from experiment-list links. **Experiments** stays visible with a disabled **Coming soon** label.
When Datasets is disabled, its tab stays disabled and direct list links show an availability message.
The chevron beside **Score trends** collapses or expands the charts. It starts expanded and remembers
your choice in local storage. Charts load on the first expansion if the page opens collapsed, and
keep their data when collapsed and expanded again. Refresh or a filter change updates loaded charts.
A shared time range, run source, and upload state filter applies to both the score charts and the experiment list.
The overview starts with the last 30 days and all upload states. Uploading and failed runs can show partial score summaries.
Projects without experiments show a full setup screen with example results and a link to the offline evals guide;
a filter with no matching experiments keeps the overview available. The offline evaluations description and tabs
stay visible on both the experiments and datasets setup screens.
Datasets, suites, and traces are optional context and are not required to display an experiment.
The compact experiment list shows the execution source in its own column and item/scorer counts together; hover over coverage for result and scorer-version counts.

**Choose scores** selects and orders recurring scorer definitions above the experiment list.
When no scores are selected, the overview selects up to three from recent completed experiments, falling back to available scorer definitions.
These choices are stored in local storage, scoped to the user and exact project/environment, and persist in that browser.
Shared URL selections and dates take precedence for that view without replacing saved choices until the user saves a customization.
The shared date picker supports presets, custom ranges, and all time.
History pages are bounded; each overview card loads at most five pages of 100 experiment/version results. The scorer history shows how many matching points are loaded.
Overview cards show the loaded count and date span when history is incomplete, and explain that earlier experiments and scorer versions may not be shown.
Different scorer versions retain their pinned configurations and are not averaged together.
Overview charts show each loaded scorer version as a separate series. Arrows browse version summaries without changing the chart.
The card summary aggregates the loaded experiments in the selected period for the selected scorer version, using the same history points as the chart. When history is partial, summaries cover only those loaded experiments.
Numeric means are weighted by successful result counts; boolean and category rates pool their counts across successful results.
Boolean charts show the passing rate, with true passing by default when polarity is omitted.
Numeric charts keep the mean as their primary metric and show the configured threshold with faint passing and failing regions. Series retain their identity colors.
Summaries and tooltips show actual passing and failing counts separately from numeric means. Pooled passing rates divide total passing results by total passing plus failing results.
Long score summaries truncate to fit their container, with the full value available on hover.
Percentage displays use at most two decimal places across summaries, charts, and tooltips. Numeric scores and means normally use six significant digits, retaining more precision when rounding would change their passing verdict. Numeric tooltips and threshold labels show the exact value.
Below the passing and failing counts, each card shows distinct experiments with the scored item count in parentheses. The item count equals passing plus failing results when a passing rule applies; otherwise it counts successful results. The experiment count includes experiments without successful scores. History is limited to 100 experiment/version results, so incomplete-history summaries cover only the loaded results.
Output types sit beside scorer titles, and neighboring charts use different colors from the theme palette.
Points are connected chronologically with smooth curves within each version and metric. Click a scorer title to open its history.
Hovering over an overview chart shows a shared vertical guide at the same execution time across the other score charts.
With a bounded date range, every chart uses that range, so the guide appears on each chart, including charts with different experiment dates.
With all time, the charts share a range from the earliest loaded result across the selected scorers to the common end time, including versions outside the currently displayed one.
The shared guide stays aligned on sparse charts, including charts with a single result.
Short date ranges show time-of-day labels, and short period comparisons show elapsed durations instead of rounded days.

An experiment shows whole-run scorer summaries and an item table with every observed scorer version.
Scroll horizontally to reach additional scorer columns.
Open an item or score cell for input, output, expected output, reasoning, and payload availability.
Boolean score cells and numeric or categorical cells with a passing rule retain their raw values or custom labels, with a success/check or danger/cross treatment based on the pinned version's rule. Execution errors use a separate warning treatment; skipped, not-applicable, missing, and numeric or categorical results without a passing rule remain neutral.
The inspector separates payload fields into collapsible labeled panels. Metadata and long text or large JSON start collapsed; each field can be expanded independently. Result details show the selected scorer and score above its reasoning.
These larger payloads load only when the inspector requests them.
Upload completion is separate from score quality. **Mark as completed** checks declared expected counts on the server; it cannot force a mismatched upload to complete.

Manage scorer definitions and versions under **Evaluations → Scorers**.
The previous Human reviews Scorers entry and bookmarked scorer URLs redirect there.
Scorer management remains available for manual reviews when offline evaluations are disabled.
Scorer names open the full-page editor at `/ai-evals/evaluations/scorers/{scorer_id}`; `/ai-evals/evaluations/scorers/new` creates a scorer.
The editor combines metadata and score configuration in one form. Passing settings are shown only when offline evaluations are enabled; hiding those controls preserves existing rules. **Save** patches metadata when configuration is unchanged; configuration changes save metadata and a new immutable version together. Saving edits to a boolean scorer with omitted or null polarity also creates a version that explicitly records the default.
Saving a new configuration checks the version observed when editing started. A concurrent version change returns 409 without saving either the draft metadata or configuration.
The **More → Create new version** action can create an unchanged configuration version after confirmation. Save or discard a dirty draft before using this action.
The **Offline evals history** button in the editor opens a scorer's experiment timeline.
With the offline feature enabled, a scorer timeline offers upload state, source, date range, comparison, and exact version filters.
Its experiment table keeps names and coverage on one line, shows execution time in its own column, and opens run details with the arrow beside each name.
Compare against a previous or custom period.
Custom comparison periods ending now retain that end when their URL is shared or reloaded.
Equal-length periods can share elapsed-time axes; unequal periods keep their actual date axes.

The `ai-observability-offline-evaluations` flag controls all new offline views and related scorer wording and links.
The legacy `llm-analytics-offline-evals` flag does not enable them. Keep rollout disabled until producer upload-to-display verification is complete.
