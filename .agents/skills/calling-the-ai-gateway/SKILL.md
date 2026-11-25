---
name: calling-the-ai-gateway
description: >
  Adds or changes a monorepo caller of the Go AI gateway (PostHog/ai-gateway). Use when adding an LLM call from Django, a Temporal or Celery worker, or a sandbox agent; when changing a caller's gateway credential, base URL, headers, attribution, or model; or when adding a task profile whose sandbox runs must mint a gateway token. Covers the `posthog/llm/gateway_client.py` builders, `phs_`/`pha_` credentials with `llm_gateway:read`, the `X-PostHog-Properties` attribution header, `SANDBOX_AI_GATEWAY_*` settings, and the `BACKGROUND_AGENTS_ORIGINS` and `MINTABLE_PRODUCTS` token gates.
---

# Calling the AI gateway

Gateway behavior (auth, billing, routing, providers, models) lives in [`PostHog/ai-gateway`](https://github.com/PostHog/ai-gateway).
A change to what the gateway does lands there. This monorepo only calls it.

## Inventory the caller

Find the call site, client construction, settings, deployment wiring, and tests. Record:

- the use case and the `ai_product` it reports as
- the credential source and the team whose wallet pays
- API shape (OpenAI or Anthropic), model, streaming, and tool or structured-output needs
- distinct ID, trace ID, session ID, and custom property attribution
- timeout, retry, and error handling

## Build the client

1. For Django and worker code, use a builder from `posthog/llm/gateway_client.py`.
   `build_openai_client`, `build_async_openai_client`, `build_anthropic_client` and `build_async_anthropic_client` authenticate with the `AI_GATEWAY_API_KEY` project secret.
   `build_ai_gateway_openai_client` sends the caller's own `pha_` or `phe_` bearer; `build_anthropic_client` also takes `privacy_mode`.
   Each raises `GatewayNotConfiguredError` when the gateway is not configured; handle it where the caller can degrade.
2. Use the slugless base URL from `AI_GATEWAY_URL` (it ends in `/v1`). The Anthropic builders strip `/v1` because the SDK appends `/v1/messages`.
3. Authenticate with a `phs_` or `pha_` credential that carries `llm_gateway:read`. Do not expose a shared secret to an untrusted runtime.
4. Send event labels in one `X-PostHog-Properties` JSON object, through the builder's `properties` argument or `ai_gateway_headers`. Use the dedicated distinct ID and trace ID arguments where the caller has them.
5. Treat `ai_product` as telemetry. It does not grant product auth or billing policy.
6. Check the model and API shape against the gateway's `/v1/models` catalog.

If the process has no gateway credential, enable the `ai-gateway` feature flag for the paying team, create a `phs_` project secret with `llm_gateway:read`, and wire it through the existing deployment secret mechanism.
Check with the AI gateway team before adding deployment variables or secrets, so existing shared configuration can be reused.

## Sandbox callers

The sandbox reaches the gateway at `SANDBOX_AI_GATEWAY_URL`, and only for products listed in `SANDBOX_AI_GATEWAY_PRODUCTS`.
[`docs/internal/sandboxes-setup-guide.md`](../../../docs/internal/sandboxes-setup-guide.md) describes those settings and the token caps.

A sandbox run reaches the gateway only when the tasks worker mints it a token.
A new task profile with `billing_product="background_agents"` must add its origin to `BACKGROUND_AGENTS_ORIGINS` in `products/tasks/backend/temporal/process_task/ai_gateway_token.py` and to `Task.SERVER_ONLY_ORIGIN_PRODUCTS`.
A missing origin is refused with `no_background_agents_provenance`, and the `tasks.gateway_token.refused` metric carries the reason.
`test_server_funded_profile_can_mint_a_gateway_token` in `products/tasks/backend/tests/test_profile_parity.py` fails until both entries exist.
A profile with a dedicated gateway product, such as `account_audit` or `autoresearch`, instead needs the product in `MINTABLE_PRODUCTS`, a provenance check in `mint_refusal`, and an entry in `GATEWAY_PRODUCTS` in `packages/agent/packages/agent/src/utils/gateway.ts`.

## Tests

Invoke `/writing-tests` before changing tests. Cover the contract at the lowest useful level:

- the selected base URL
- the credential and required headers, without asserting secret values
- the `X-PostHog-Properties` JSON and trace attribution
- the model and API shape
- the failure behavior the caller handles, including `GatewayNotConfiguredError`

## Verify

Run the narrow caller tests and the formatter or type checker for touched code.
Exercise a real request against a local gateway (`hogli start` with the `ai_gateway` capability, or `bin/setup-gateway-e2e`) when credentials are available, and confirm the generation's attribution.
