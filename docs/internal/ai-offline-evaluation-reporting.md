# Offline evaluation result reporting

The sandboxed evaluation harness in `products/posthog_ai/eval_harness/` reports scorer results as PostHog `$ai_evaluation` events.
With the Braintrust engine, each suite runs once and the harness sends the resulting scores to PostHog after the run.
Reporting does not run the agent or scorers again.

## Capture settings

The harness uses a dedicated client for evaluation result events.
This client permits `$ai_evaluation` reporting when `TEST=1`, which the harness uses for its test database setup.
Ordinary PostHog SDK clients and trace clients retain their existing capture guards.

Set `OPT_OUT_CAPTURE` to any nonempty value to disable PostHog result reporting.
Values such as `0` and `false` also opt out, matching the existing capture helper.
Leave the variable unset or empty to allow result reporting.

## Result contents and scope

Each event contains the existing experiment, case, and metric properties, including input, output, and expected values when available.
Result reporting uses the existing event schema.
`SandboxedPublicEval` uploads results to Braintrust, and `SandboxedPrivateEval` sets `no_send_logs=True` for Braintrust.
Both report results to PostHog unless `OPT_OUT_CAPTURE` is set; the Braintrust upload setting does not control PostHog reporting.
The legacy SQL evaluation path in `ee/hogai/eval/offline/` has a separate reporter and is outside this behavior.
