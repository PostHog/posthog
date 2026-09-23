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
Launches are disabled unless `SCOUT_LIVE_TRIALS_ENABLED`, `SCOUT_LIVE_TRIALS_PRIVATE_CAPTURE`, and `SCOUT_LIVE_TRIALS_GATEWAY_URL` are configured.
The private-capture setting attests that the selected gateway and query/task data destinations are isolated from the project the scouts inspect.
Use a dedicated gateway with its PostHog capture token empty; also check warehouse replicas before enabling trials on a deployment.
Rate limits still apply, but shared generation events cannot supply trial costs when capture is disabled.
Results report unknown cost as null and retain runtime token counts when available.
Operator trial MCP tools also omit analytics payloads.
Task content retrieval tools retain call metrics but omit content spans and free-text intent, so viewing a private transcript does not publish it through MCP analytics.

The [live comparison plan and script](../../products/signals/eval/experiments/2026-09-long-running-agent-evals/PLAN.md#live-trial-operator-script) describe launch inputs, stored results, and supported scout capabilities.
Keep downloaded prompts, memory, reports, and transcripts outside version control.
