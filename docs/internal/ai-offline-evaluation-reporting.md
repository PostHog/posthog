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
