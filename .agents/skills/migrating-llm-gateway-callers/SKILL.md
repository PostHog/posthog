---
name: migrating-llm-gateway-callers
description: >
  Guides migration from services/llm-gateway to PostHog/ai-gateway and refreshes the gateway parity record. Use when adding or migrating an LLM caller; changing either gateway's auth, attribution, billing, endpoint, provider, model, routing, or metadata contract; modifying posthog/llm/gateway_client.py or gateway settings; reviewing a services/llm-gateway change; or updating services/llm-gateway/PARITY.md.
---

# Migrating LLM gateway callers

The Go gateway is the default. Treat `services/llm-gateway` as frozen unless an active caller is blocked by a verified parity gap.

Read [`services/llm-gateway/PARITY.md`](../../../services/llm-gateway/PARITY.md) before changing a caller or either gateway contract.

## Decide where work belongs

1. Describe the caller's identity, billing owner, API shape, model, provider, metadata, and failure requirements.
2. Match those requirements against the use-case and parity tables in `PARITY.md`.
3. Use the Go gateway when every required contract is supported.
4. Keep or change the Python gateway only for a named blocker that affects an active caller.

An existing Python integration is not a blocker by itself. Prefer a shared builder in `posthog/llm/gateway_client.py` when it supports the caller.

## Gate Python gateway changes

Before editing `services/llm-gateway`, establish all of the following:

- The active caller and user-visible or operational need are known.
- The missing Go contract is identified from implementation evidence.
- Implementing or waiting for the Go contract is not suitable for this change.
- The Python change is limited to the blocker and does not create a broader competing feature.
- The PR explains the blocker and migration condition.

If the Go gateway already supports the contract, migrate the caller instead. If neither gateway supports it, add it to Go unless the blocked caller needs a temporary Python fix.

## Refresh parity from source

Audit current default branches. Do not rely on the existing parity table or README summaries alone.

### 1. Record source revisions

- Record `origin/master` for `PostHog/posthog`.
- Read the current `PostHog/ai-gateway` main SHA with `gh api repos/PostHog/ai-gateway/commits/main`.
- Use an authenticated checkout of `PostHog/ai-gateway` when code inspection is needed.

### 2. Inspect the contracts

For the Python gateway, inspect:

- `services/llm-gateway/src/llm_gateway/api/` for routes and wire behavior
- `services/llm-gateway/src/llm_gateway/auth/` for accepted credentials
- `services/llm-gateway/src/llm_gateway/products/config.py` for trusted product policy, models, and billing
- `services/llm-gateway/src/llm_gateway/rate_limiting/` for budgets and limits
- `services/llm-gateway/src/llm_gateway/callbacks/` for event attribution
- `posthog/llm/gateway_client.py` and real call sites for migration needs

For the Go gateway, inspect:

- `internal/httpapi/routes.go` and dispatch packages for API shapes
- `internal/auth/` and `internal/principal/` for credential and identity policy
- `internal/httpapi/admission.go`, `internal/ledger/`, and `internal/quota/` for billing and limits
- `internal/catalog/`, `internal/router/`, and `internal/dispatch/` for models, providers, translation, and failover
- `internal/emitter/` and request parsing for attribution and metadata
- `docs/product.md` for intended contracts and explicitly deferred work, verified against code

### 3. Classify each difference

- ✅ **Supported:** a caller can migrate without losing a required contract.
- ⛔ **Blocking:** an active use case would lose auth, trusted attribution, billing policy, API, provider, or wire behavior.
- 🔎 **Verify:** support exists, but the caller must confirm configuration or behavior.

Do not call telemetry labels trusted attribution. A caller-supplied `ai_product` property does not replace product authentication, authorization, or billing policy.

### 4. Update the parity record

Update `services/llm-gateway/PARITY.md` when evidence changes:

- Move use cases between sections.
- Add or remove only migration-relevant contracts.
- Update the source SHAs and verification date.
- Keep the document decision-oriented. Put detailed Go design in `PostHog/ai-gateway`.

When a gap closes, identify PostHog callers that can migrate. A parity refresh is incomplete if the table changes but obvious affected callers remain unmentioned in the PR.

## Validate

Run:

```sh
pnpm exec oxfmt services/llm-gateway/PARITY.md .agents/skills/migrating-llm-gateway-callers/SKILL.md
pnpm exec markdownlint-cli2 --config .config/.markdownlint-cli2.jsonc services/llm-gateway/PARITY.md .agents/skills/migrating-llm-gateway-callers/SKILL.md
git diff --check
```
