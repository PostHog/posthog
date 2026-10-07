# Offline evaluation result reporting

The sandboxed evaluation harness in `products/posthog_ai/eval_harness/` reports scorer results as PostHog `$ai_evaluation` events.
With the Braintrust engine, each suite runs once and the harness sends the resulting scores to PostHog when uploads are enabled.
The SQL suite can also publish those results to the offline experiment API while retaining both existing destinations.
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

## SQL offline experiment pilot

The `sql/eval_sql::eval_sql` suite (`sandboxed-sql-cli`) opts into the offline experiment publisher.
Other suites continue using Braintrust and the existing event reporting path.
The publisher runs after scoring and uses the same per-case results; it does not execute another agent run or judge call.
`no_send_logs=True` suppresses this upload too.

Configure the destination through the environment before running the SQL suite:

| Variable                               | Purpose                                                                                                                                             |
| -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| `POSTHOG_OFFLINE_EVAL_API_KEY`         | Personal or project secret API key with `offline_evaluation_ingestion:write`. A public project token cannot authenticate uploads.                   |
| `POSTHOG_OFFLINE_EVAL_PROJECT_ID`      | Exact destination project/environment ID.                                                                                                           |
| `POSTHOG_OFFLINE_EVAL_SCORER_VERSIONS` | JSON object mapping each of the seven metric names below to an existing immutable scorer **version UUID**, not a definition UUID or version number. |
| `POSTHOG_OFFLINE_EVAL_HOST`            | App origin; defaults to `https://us.posthog.com`.                                                                                                   |

Create the scorer definitions in the destination project before configuring their versions:

| Metric name                          | Scorer kind                      |
| ------------------------------------ | -------------------------------- |
| `exit_code_zero`                     | Boolean                          |
| `no_persistent_insight_save`         | Boolean                          |
| `execute_sql_called`                 | Boolean                          |
| `answer_tool_not_typed_query`        | Boolean                          |
| `querying_posthog_data_skill_loaded` | Boolean                          |
| `sql_schema_alignment`               | Numeric, minimum 0 and maximum 1 |
| `sql_result_message_alignment`       | Numeric, minimum 0 and maximum 1 |

For example, the mapping has this shape. Replace every placeholder with the corresponding version UUID returned by the scorer API or MCP:

```bash
export POSTHOG_OFFLINE_EVAL_SCORER_VERSIONS='{
  "exit_code_zero": "00000000-0000-4000-8000-000000000001",
  "no_persistent_insight_save": "00000000-0000-4000-8000-000000000002",
  "execute_sql_called": "00000000-0000-4000-8000-000000000003",
  "answer_tool_not_typed_query": "00000000-0000-4000-8000-000000000004",
  "querying_posthog_data_skill_loaded": "00000000-0000-4000-8000-000000000005",
  "sql_schema_alignment": "00000000-0000-4000-8000-000000000006",
  "sql_result_message_alignment": "00000000-0000-4000-8000-000000000007"
}'
hogli evals sql/eval_sql::eval_sql
```

Without publishing configuration, the SQL run reports that offline uploads are disabled.
Partial or invalid configuration produces a warning and skips this destination; Braintrust and legacy event reporting continue.
An upload failure also warns without changing the evaluation's score gate.

Each case and trial becomes a separate item, with one result per configured scorer.
Boolean scores convert `0` and `1` to `false` and `true`; numeric scores retain their values.
Both `false` and numeric zero have status `ok`: this status means scoring produced a value, not that the agent passed.
A `None` score becomes `skipped`; a task error or missing scorer result becomes `error`, with no score value.
The judges' existing error fallback of zero remains zero, matching Braintrust's score.
Successful scorer reasoning is not available in the engine's returned results and is not uploaded by this pilot.

Items include available input, output, expected output, and case metadata.
The publisher excludes `raw_log` from the new API payload; the existing local logs and Braintrust output retain it.
Fields that exceed payload limits are omitted, with omission details recorded in metadata.

The publisher saves the exact create and upload requests in `posthog-offline-upload.json` inside the experiment's agent-log directory before sending them.
Transient failures receive at most three attempts with the same experiment and item identities.
After correcting a configuration or connectivity problem, replay the saved requests without rerunning the eval:

```bash
python -m products.posthog_ai.eval_harness.offline_results PATH_TO_posthog-offline-upload.json
```

Replay uses the API key, host, and project environment settings for the original destination.
It retains the saved scorer version UUIDs regardless of the current `POSTHOG_OFFLINE_EVAL_SCORER_VERSIONS` mapping, then completes the experiment after all uploads succeed.

## Postgres experiment ingestion

The project API accepts offline experiment results behind the `ai-observability-offline-evaluations` feature flag.
The configured SQL pilot calls this API in addition to the harness's existing event capture.

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
The offline UI uses these APIs. The configured SQL pilot publishes results here; legacy `$ai_evaluation` events do not populate these views.

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
A shared time range, run source, and upload state filter applies to both the score charts and the experiment list.
The overview starts with the last 30 days and all upload states. Uploading and failed runs can show partial score summaries.
Projects without experiments show setup steps; a filter with no matching experiments keeps the overview available.
Datasets, suites, and traces are optional context and are not required to display an experiment.
The compact experiment list shows the execution source in its own column and item/scorer counts together; hover over coverage for result and scorer-version counts.

**Choose scores** selects and orders recurring scorer definitions above the experiment list.
When no scores are selected, the overview selects up to three from recent completed experiments, falling back to available scorer definitions.
These choices are stored in local storage, scoped to the user and exact project/environment, and persist in that browser.
Shared URL selections and dates take precedence for that view without replacing saved choices until the user saves a customization.
The shared date picker supports presets, custom ranges, and all time.
History pages are bounded; the scorer history shows how many matching points are loaded.
Overview cards show the loaded count and date span when history is incomplete, and explain that earlier experiments and scorer versions may not be shown.
Different scorer versions retain their pinned configurations and are not averaged together.
Overview cards show one version at a time, with arrows to browse versions that have results in the selected period.
The card summary aggregates the loaded experiments in the selected period for the displayed scorer version, using the same history points as the chart.
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
