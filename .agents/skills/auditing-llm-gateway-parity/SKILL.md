---
name: auditing-llm-gateway-parity
description: >
  Audits services/llm-gateway against PostHog/ai-gateway and updates services/llm-gateway/PARITY.md from current implementation evidence. Use when either gateway changes auth, attribution, billing, endpoints, providers, models, routing, or metadata; when reviewing a Python gateway change; or when asked to refresh, verify, or report gateway parity. This skill updates the parity record but does not migrate callers.
---

# Auditing LLM gateway parity

Compare the current implementations of both gateways and update [`services/llm-gateway/PARITY.md`](../../../services/llm-gateway/PARITY.md). Keep this audit separate from caller migration.

## Record source revisions

- Fetch `origin/master` and record its SHA as the PostHog baseline.
- Audit the current working tree, including committed and uncommitted changes relative to that baseline. Do not ignore an in-flight gateway change because it is not on `master` yet.
- Read the current `PostHog/ai-gateway` main SHA with `gh api repos/PostHog/ai-gateway/commits/main` and record it as the Go baseline.
- If the audit is for an in-flight Go change, inspect that PR branch or working tree relative to `main`. Treat its contracts as pending until the change merges; do not record them as currently supported.
- Otherwise, inspect an authenticated checkout of `PostHog/ai-gateway` at `main`.

Audit implementation code. README files and the existing parity table are starting points, not proof.

## Inspect each contract

For the Python gateway, inspect:

- `services/llm-gateway/src/llm_gateway/api/` for routes and wire behavior
- `services/llm-gateway/src/llm_gateway/auth/` for accepted credentials
- `services/llm-gateway/src/llm_gateway/db/required_tables.py` for the tables the gateway may read; a change adding a table read needs its posthog-cloud-infra SELECT grant landed in every environment first
- `services/llm-gateway/src/llm_gateway/products/config.py` for trusted product policy, models, and billing
- `services/llm-gateway/src/llm_gateway/rate_limiting/` for budgets and limits
- `services/llm-gateway/src/llm_gateway/callbacks/` for event attribution
- `posthog/llm/gateway_client.py` and real call sites for required contracts

For the Go gateway, inspect:

- `internal/httpapi/routes.go` and dispatch packages for API shapes
- `internal/auth/` and `internal/principal/` for credential and identity policy
- `internal/httpapi/admission.go`, `internal/ledger/`, and `internal/quota/` for billing and limits
- `internal/catalog/`, `internal/router/`, and `internal/dispatch/` for models, providers, translation, and failover
- `internal/emitter/` and request parsing for attribution and metadata
- `docs/product.md` for intended and deferred contracts, verified against code

Check both request and response behavior. Matching route names do not prove parity for headers, streaming, errors, timeouts, retries, billing, or emitted events.

## Classify the evidence

- ✅ **Supported:** the Go gateway satisfies the contract.
- ⛔ **Blocking:** an active use case would lose auth, trusted attribution, billing policy, API, provider, or wire behavior.
- 🔎 **Verify:** support exists, but a caller must confirm configuration or behavior.

Do not treat caller-supplied telemetry as trusted policy. An `ai_product` event property does not replace product authentication, authorization, or billing.

Do not treat Python's unbilled flag as an automatic blocker. An internal workload can move to Go with a PostHog-owned team credential when debiting that wallet is the intended way to attribute PostHog spend. It is blocked only when it must preserve customer-specific billing policy or must debit no wallet.

For each difference, identify at least one affected use-case class. Remove details that do not change a migration decision.

## Update the parity record

Update `services/llm-gateway/PARITY.md` with the evidence:

- Move use cases between supported, blocked, and verify sections.
- Add or remove migration-relevant contracts in the parity map.
- Update the source SHAs and verification date.
- Keep detailed Go design in `PostHog/ai-gateway`.

When a gap closes, name obvious caller classes that are newly eligible to migrate. Do not modify those callers unless the user also asks for migration work. Use `/migrating-llm-gateway-callers` for that separate job.

## Validate

Run:

```sh
pnpm exec oxfmt services/llm-gateway/PARITY.md .agents/skills/auditing-llm-gateway-parity/SKILL.md
pnpm exec markdownlint-cli2 --config .config/.markdownlint-cli2.jsonc services/llm-gateway/PARITY.md .agents/skills/auditing-llm-gateway-parity/SKILL.md
git diff --check
```
