# Publishing offline results

The MCP ingestion tools store results from an evaluator executed by the user's
application, local script, or CI job. They do not execute that evaluator. Never
invent outputs or scores to fill a run. Use the REST API for bulk producer uploads;
MCP is useful for small submissions and lifecycle operations.

The `posthog:llma-offline-experiment-*` tools below exist only in projects where
offline evaluations are enabled. If they are not in the tool list, stop and tell the user.

## Prepare stable identities

Find or create a scorer with `posthog:llma-score-definition-list`,
`posthog:llma-score-definition-get`, or `posthog:llma-score-definition-create`.
A scorer defines the value kind and grading configuration, not executable evaluator
code. Pin `current_version_id` or an exact historical version UUID. Use
`posthog:llma-score-definition-new-version` with the observed `base_version` when
rules change; `posthog:llma-score-definition-update` edits metadata or archival state.

If linking a hosted dataset, use existing dataset/revision tools to resolve its
revision and each active item-version UUID. Scorers and datasets must belong to the
same project/environment as the experiment. External dataset identifiers are also
supported; a hosted dataset is not required.

Generate an experiment UUID and item UUIDs once and retain them for retries. Capture
the actual execution start time and suite/dataset/application/model/prompt revisions.
One item represents an input/output execution; multiple scorers share that item.
Repeated trials need distinct item IDs and useful case/trial identities.

## Create, upload, and close

1. Call `posthog:llma-offline-experiment-create` with the experiment UUID, name, and
   `started_at`. Declare expected item/result counts when known. These declarations
   are immutable; result counts include non-success outcomes.
2. Call `posthog:llma-offline-experiment-upload` with small batches. It accepts
   1–1,000 results and up to 1,000 item declarations atomically. Results identify
   `item_id` and `scorer_version_id`; their pair is unique in an experiment.
   Declare an item on its first upload, then reference it without repeating content.
3. Use `ok` with a typed `value` for successfully evaluated results, even when the
   score fails the passing rule. Use `error`, `skipped`, or `not_applicable` for their
   respective execution outcomes. Preserve the distinction between omitted payload
   properties, empty objects, and explicit JSON nulls.
4. After every result is acknowledged, call `posthog:llma-offline-experiment-complete`.
   A count mismatch returns 409 and leaves the experiment uploading: reconcile the
   acknowledged results and intended counts. Completing does not mean every score passed.
5. Use `posthog:llma-offline-experiment-fail` only for an interrupted execution or
   upload, retaining partial results. Both closure operations are terminal: new
   items/results cannot be added afterward.

On an uncertain response, retry the same IDs and identical content. Exact retries
remain valid after closure. Changed immutable content produces a conflict; do not
silently create new IDs to evade it. Fix validation errors before retrying a rejected
batch. Treat 403 as a permission problem rather than retrying with a broader credential.

Ingestion requires `offline_evaluation_ingestion:write`; it grants neither payload
reads nor scorer administration. Project secret API keys are ingestion-only here.
An agent can upload results without being able to read them back, so acknowledgments
are the source of truth for upload success.
