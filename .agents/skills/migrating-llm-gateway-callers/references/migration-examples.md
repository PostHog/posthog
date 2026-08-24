# Migration examples

These PRs show different migration shapes. Read the relevant diff before implementing a similar change because gateway contracts have continued to evolve. Use them for implementation decisions, not as an inventory of current rollout state.

## Django and direct-provider callers

- [#64448: make cluster labeling routable through the AI gateway](https://github.com/PostHog/posthog/pull/64448) introduces an environment-gated OpenAI client, validates paired settings, preserves direct-provider fallback, checks model availability before rollout, and tests both routes.
- [#65043: route the eval-report agent through the AI gateway](https://github.com/PostHog/posthog/pull/65043) moves the AI observability eval-report agent after the shared route exists and tests the selected client path.
- [#65044: route OpenAI summarization through the AI gateway](https://github.com/PostHog/posthog/pull/65044) extracts shared sync and async builders, uses the slugless Go URL and project secret, keeps `trust_env=False`, retains the Python fallback, and prevents duplicate `$ai_generation` capture.

## Incremental product rollout

- [#71947: add the Signals AI gateway client and per-call opt-in](https://github.com/PostHog/posthog/pull/71947) adds the Anthropic builder and an opt-in seam without moving traffic. It converts per-key metadata to `X-PostHog-Properties`, strips `/v1` for the Anthropic SDK, and preserves Python behavior for callers that have not opted in.
- [#71948: route Signals grouping through the AI gateway](https://github.com/PostHog/posthog/pull/71948) uses that seam to move one workload at a time. Reverting the small opt-in returns only grouping to Python.
- [#71949: route Signals emission stages through the AI gateway](https://github.com/PostHog/posthog/pull/71949) handles batch and per-call metadata explicitly. Its tests cover both the Go JSON properties blob and Python per-key fallback headers.
- [#71950: route Signals safety through the AI gateway](https://github.com/PostHog/posthog/pull/71950) opts the safety filter and report safety judge into the shared Go-capable client.
- [#71951: route Signals eval summarization through the AI gateway](https://github.com/PostHog/posthog/pull/71951) applies the same narrow per-call rollout to eval summaries.
- [#72769: tag eval-fixture generation as `signals_eval`](https://github.com/PostHog/posthog/pull/72769) preserves workload attribution for Signals eval generation.

## Sandbox and deployment wiring

- [#72770: route selected sandbox products to the AI gateway](https://github.com/PostHog/posthog/pull/72770) treats migration as more than a client change. It pairs URL and product rollout settings, reserves them against user overrides, updates both egress enforcement layers, validates configured hostnames, extends startup diagnostics, and keeps rollback to clearing either setting.

## Cross-repository patterns

### Standalone TypeScript service

1. [PostHog/SherlockHog #104: route the agent through the slugless AI gateway](https://github.com/PostHog/SherlockHog/pull/104) adds the paired Go settings, base URL translation, project-secret auth, Python fallback, and route-selection tests for a TypeScript Claude Agent SDK service.
2. [PostHog/SherlockHog #111: boot with either complete gateway pair](https://github.com/PostHog/SherlockHog/pull/111) fixes the transitional startup contract so an AI-gateway-only deployment can boot while preserving the Python rollback route.
3. [PostHog/SherlockHog #112: tag the AI product through `X-PostHog-Properties`](https://github.com/PostHog/SherlockHog/pull/112) corrects attribution after the initial cutover reused Python's per-property headers. It keeps each gateway's metadata format separate and verifies that the Go route no longer emits the legacy form.
4. [PostHog/charts #12919: cut development over to the slugless AI gateway](https://github.com/PostHog/charts/pull/12919) wires the development URL and secret first, with explicit deployment rendering and rollback checks.
5. [PostHog/charts #12920: cut production over to the slugless AI gateway](https://github.com/PostHog/charts/pull/12920) applies the regional production configuration after the development stage.

Together these show the client, transitional boot contract, attribution correction, staged deployment, and rollback boundaries.

### Per-product sandbox routing

1. [PostHog/code #3659: route selected products to the AI gateway](https://github.com/PostHog/code/pull/3659) selects a gateway per sandbox request. It requires both the Go URL and an allowlist, keeps unlisted products on Python, converts attribution to one bounded ASCII-safe JSON header, and gives each workload a distinct product tag.
2. [PostHog/posthog #72770: route selected sandbox products to the AI gateway](https://github.com/PostHog/posthog/pull/72770) passes the settings into sandboxes, reserves them against user overrides, updates both egress enforcement layers, validates configured hostnames, and extends startup diagnostics.
3. [PostHog/charts #13358: route Signals sandbox stages in development](https://github.com/PostHog/charts/pull/13358) activates the client and Django support for four workloads in development.

These show how to select Go per request, pass configuration through a sandbox boundary, enforce egress, and activate a narrow set of workloads.

### Standalone PR-review agent

- [PostHog/posthog #68329: route the PR-approval agent through the AI gateway](https://github.com/PostHog/posthog/pull/68329) and [PostHog/code #3354: route PR review through the AI gateway](https://github.com/PostHog/code/pull/3354) validate paired settings, strip `/v1` before the SDK restores its messages path, set both Anthropic auth variables, avoid duplicate capture by bypassing the traced wrapper in gateway mode, and retain an explicit fallback.

### Deployment activation

- [PostHog/charts #13131: repoint worker deployments to the AI gateway](https://github.com/PostHog/charts/pull/13131) demonstrates that merged client support does not move traffic by itself. It wires the regional URL and app-specific secret into every deployment that runs an already-migrated caller, with removal of either setting as rollback. Use it as deployment guidance, not as a standalone caller migration.

## Post-migration parity checks

- [#74249: send a stable team trace ID to the Go gateway](https://github.com/PostHog/posthog/pull/74249) fixes trace fragmentation found after a migration. It matches Python's existing trace derivation, sends the dedicated Go header, and pins cross-gateway compatibility with fixed expected IDs.

Use these examples for their decisions and verification boundaries. Re-check [`services/llm-gateway/PARITY.md`](../../../../services/llm-gateway/PARITY.md) before adopting an older pattern.
