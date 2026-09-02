---
name: migrating-llm-gateway-callers
description: >
  Migrates an LLM caller from services/llm-gateway to PostHog/ai-gateway. Use when adding a gateway caller, converting an existing Python gateway integration, adopting shared Go-capable client builders, changing gateway URLs or headers for a caller, or removing a Python fallback. Inventories the caller's contract, checks the parity record, implements the supported migration, updates tests, and stops with a documented blocker when Go parity is missing.
---

# Migrating LLM gateway callers

Use [`services/llm-gateway/PARITY.md`](../../../services/llm-gateway/PARITY.md) as the current decision record. If it is stale or the migration reveals a new gap, run `/auditing-llm-gateway-parity` before continuing.

## Inventory the caller

Find the production call site, client construction, settings, deployment wiring, and tests. Record:

- caller and user-facing use case
- credential source and required authorization policy
- spend owner, budgets, current Python billing behavior, and the team wallet that should own Go spend
- API shape, model, provider, streaming, and tool or structured-output requirements
- distinct ID, trace, product, team, feature flag, and custom property attribution
- timeout, retry, fallback, and error-handling behavior
- usage or quota APIs read by the caller

Search for the product name, `LLM_GATEWAY`, `AI_GATEWAY`, gateway client helpers, and gateway headers. Follow configuration into sandbox or deployment code when the call does not run in Django.

## Check whether migration is supported

Match every required contract to the parity record and current code.

- If all required contracts are supported, continue with the migration.
- If a 🔎 item applies, verify it against the caller's actual model, request, and configuration.
- If a ⛔ gap applies, stop the migration. Report the exact blocker and keep the Python path.

An existing Python client or product route is not a blocker by itself.

Python's unbilled flag is not a blocker when an internal workload should debit a PostHog-owned team wallet for spend attribution. Confirm that the Go credential resolves to that team. Stop only when migration would charge a customer incorrectly, lose required customer budget policy, or violate a requirement to debit no wallet.

## Implement the migration

Prefer the smallest existing pattern that matches the caller:

Read [migration examples](references/migration-examples.md) for verified PRs covering Django clients, staged workload rollout, sandbox wiring, and attribution continuity. Follow the contract demonstrated by the relevant example rather than copying its code mechanically.

1. Use `build_openai_client`, `build_async_openai_client`, or `build_async_anthropic_client` from `posthog/llm/gateway_client.py` for Django callers when possible.
2. Use the slugless Go base URL. Do not carry a Python `/{product}/` path into the Go URL.
3. Use a supported `phs_` or `pha_` credential with `llm_gateway:read`. Do not weaken auth or expose a shared secret to an untrusted runtime.
4. Send event labels in one `X-PostHog-Properties` JSON object. Use the dedicated distinct ID and trace ID headers where required.
5. Treat `ai_product` as telemetry only. Do not use it to replace trusted product auth or billing policy.
6. Confirm the canonical model and API shape against the Go model catalog.
7. Preserve the caller's provider and fallback requirements. Use provider pinning only when the caller requires a specific host.
8. Keep a Python fallback only when rollout needs it, and make the switch explicit in settings or the shared builder.

For sandbox callers, follow the existing `SANDBOX_AI_GATEWAY_URL` and product rollout patterns rather than inventing another environment contract.

For internal products, check with the AI gateway team before adding deployment variables or secrets so existing shared configuration can be reused.

If the target process does not have a Go credential, enable the `ai-gateway` feature flag for the intended paying team, then create a `phs_` project secret in the PostHog dashboard with `llm_gateway:read` and wire it through the existing deployment secret mechanism. Credential creation is normal migration work, not a parity exception.

## Update tests and docs

Invoke `/writing-tests` before changing tests.

Cover the observable migration contract at the lowest useful level:

- selected base URL and absence of the Python product slug
- credential and required headers without asserting secret values
- converted JSON properties and trace attribution
- model and API shape
- rollout fallback when one remains
- failure behavior the caller handles

Update nearby docs and settings descriptions when the operator workflow changes. Do not update the parity record unless implementation evidence changed; use `/auditing-llm-gateway-parity` when it did.

## Verify

Run the narrow caller tests and the formatter or type checker for touched code. Exercise a real request when credentials and a safe development gateway are available. Confirm the event attribution and billing behavior when those contracts matter.

Before handing off, summarize:

- migrated caller and use case
- Go contracts relied on
- fallback left in place, if any
- parity blocker, if migration stopped
- checks run and any environment limitation
