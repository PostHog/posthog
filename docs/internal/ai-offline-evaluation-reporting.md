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
Backend report validation uses a short-lived credential with only gateway access and the experiment identity; it is revoked after the operation.
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

The [mock rubric fixture](../../products/signals/eval/experiments/2026-09-long-running-agent-evals/fixtures/mock-scout-rubric.json) matches the read response in [the scout rubric editor PR](https://github.com/PostHog/posthog/pull/106580), checked at `d7c6c3742ba`.
It contains the six default criteria, `revision: 0` (unsaved defaults), and `generation: null`.
These are mock inputs for developing scoring and reports, not a saved or reviewed rubric for the selected scout.

Print a mock response for a scout:

```sh
python products/signals/eval/experiments/2026-09-long-running-agent-evals/scripts/scout_rubric_reader.py \
  --config-id 00000000-0000-4000-8000-000000000001 \
  --skill-name signals-scout-example
```

Comparison code can accept `ScoutRubricReader` and explicitly use `MockScoutRubricReader` from that script.
`read(config_id=..., skill_name=...)` returns a fresh document with the supplied scout identity and the API's unchanged field names.
The reader does not write scout configuration, generate criteria, or score runs.

When the real rubric API is available, replace the mock reader with a reader for `GET /api/projects/{team_id}/signals/scout/rubrics/{config_id}/`, preserving that response shape.
Keep the editor, storage, and generation in the rubric feature; do not add a second implementation to comparisons.
The real reader must propagate missing-rubric and access errors rather than falling back to mock criteria.

Persist the returned criteria and revision with the comparison before judging, so every variant uses the same rubric.
Record `source: mock` separately from the API document, and never label mock results as a reviewed scout evaluation.
Judge only enabled saved/default `criteria`; `generation.suggestions` are drafts, and missing evidence is not a passing score.

### Internal comparison UI

Staff members in project 2 can open **Scouts > Compare scouts** to choose a scout, add prompt/model/effort variants, and set the number of runs per variant.
The page submits at most 20 runs per comparison and shows deployment or scout compatibility blockers before launch.
The first accepted launch saves the shared starting history; remaining launches reuse it with their own private writable state.
Keep the page open until all submissions are confirmed. Accepted runs continue on the server after the page closes.

The page shows the operator's recent private runs, supports stopping active runs, and exports their captured reports, memory changes, and available usage as JSON.
Browser storage keeps only scout and launch IDs, scoped to the project and operator.
Unsubmitted prompt edits are lost on reload; start a new comparison instead of reconstructing an uncertain request.
The setup and history endpoints enforce the staff/project restriction on the server, in addition to existing scout permissions.
Shared instructions guide investigations but do not enforce date or file access limits.
