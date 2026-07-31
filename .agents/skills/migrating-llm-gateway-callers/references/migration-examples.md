# Migration examples

These merged PRs show different migration shapes. Read the relevant diff before implementing a similar change because gateway contracts have continued to evolve.

## Django and direct-provider callers

- [#64448: make cluster labeling routable through the AI gateway](https://github.com/PostHog/posthog/pull/64448) introduces an environment-gated OpenAI client, validates paired settings, preserves direct-provider fallback, checks model availability before rollout, and tests both routes.
- [#65044: route OpenAI summarization through the AI gateway](https://github.com/PostHog/posthog/pull/65044) extracts shared sync and async builders, uses the slugless Go URL and project secret, keeps `trust_env=False`, retains the Python fallback, and prevents duplicate `$ai_generation` capture.
- [#68329: route the PR-approval agent through the AI gateway](https://github.com/PostHog/posthog/pull/68329) covers a non-Django SDK process. It validates and translates gateway environment variables, switches away from the traced SDK wrapper in gateway mode, keeps a direct fallback, and tests credential and metadata wiring without exposing secret values.

## Incremental product rollout

- [#71947: add the Signals AI gateway client and per-call opt-in](https://github.com/PostHog/posthog/pull/71947) adds the Anthropic builder and an opt-in seam without moving traffic. It converts per-key metadata to `X-PostHog-Properties`, strips `/v1` for the Anthropic SDK, and preserves Python behavior for callers that have not opted in.
- [#71948: route Signals grouping through the AI gateway](https://github.com/PostHog/posthog/pull/71948) uses that seam to move one workload at a time. Reverting the small opt-in returns only grouping to Python.
- [#71949: route Signals emission stages through the AI gateway](https://github.com/PostHog/posthog/pull/71949) handles batch and per-call metadata explicitly. Its tests cover both the Go JSON properties blob and Python per-key fallback headers.

## Sandbox and deployment wiring

- [#72770: route selected sandbox products to the AI gateway](https://github.com/PostHog/posthog/pull/72770) treats migration as more than a client change. It pairs URL and product rollout settings, reserves them against user overrides, updates both egress enforcement layers, validates configured hostnames, extends startup diagnostics, and keeps rollback to clearing either setting.

## Post-migration parity checks

- [#74249: send a stable team trace ID to the Go gateway](https://github.com/PostHog/posthog/pull/74249) fixes trace fragmentation found after a migration. It matches Python's existing trace derivation, sends the dedicated Go header, and pins cross-gateway compatibility with fixed expected IDs.

Use these examples for their decisions and verification boundaries. Re-check [`services/llm-gateway/PARITY.md`](../../../../services/llm-gateway/PARITY.md) before adopting an older pattern.
