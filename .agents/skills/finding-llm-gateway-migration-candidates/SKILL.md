---
name: finding-llm-gateway-migration-candidates
description: >
  Finds and ranks callers that could move from services/llm-gateway to PostHog/ai-gateway. Use when asked what to migrate next, to find low-risk gateway migration candidates, to audit remaining Python gateway callers, or to identify callers blocked by Go gateway parity. Searches code and deployment wiring, inventories each caller's required contract, filters out unsupported migrations, and returns an evidence-backed shortlist without changing callers.
---

# Finding LLM gateway migration candidates

Use [`services/llm-gateway/PARITY.md`](../../../services/llm-gateway/PARITY.md) as the current contract decision record. If implementation evidence contradicts it, run `/auditing-llm-gateway-parity` before ranking candidates.

This skill produces a point-in-time shortlist. Do not turn the parity document into a fleet-wide migration tracker.

## Discover callers

Search the current default branches for Python gateway use, including:

- `LLM_GATEWAY_URL`, `LLM_GATEWAY_API_KEY`, and product-slug URLs
- `get_llm_client`, `get_async_llm_client`, and `get_async_anthropic_gateway_client`
- direct OpenAI, Anthropic, or agent SDK clients configured with a gateway base URL
- Python product names from `services/llm-gateway/src/llm_gateway/products/config.py`
- deployment, sandbox, workflow, and secret wiring in other PostHog repositories

Trace each result to the production call site. Exclude tests, development-only tools, dead code, and callers already configured exclusively for Go. Treat shared worker configuration as evidence about availability, not proof that every call in that process uses Go.

Search open and recently merged PRs across involved repositories before proposing work. A migration may already be underway even when the default branch still uses Python.

## Prove the production path

Before classifying a caller, follow it through every runtime boundary:

1. Find the API, task, workflow, schedule, or command that invokes it.
2. For Temporal, map the workflow and activity to the exact task queue, then map that queue to its deployed worker.
3. Inspect every environment overlay that runs the caller. Do not borrow configuration from another worker in the same product.
4. Resolve the configured URL by host and path. Variable names are not proof: an `AI_GATEWAY_URL` can still contain a Python product-slug URL.
5. Confirm the current call can succeed. A broad exception handler with a deterministic fallback can hide missing credentials or a route that never runs.

A missing `phs_` credential is deployment work, not a parity blocker. Once the intended paying team is known, create a project secret with `llm_gateway:read` in the PostHog dashboard and fund or configure that team wallet as part of the migration. A secret reference proves only that a credential is injected; verify ownership, scope, and funding during implementation or rollout.

## Inventory each candidate

Record only the contracts that affect the migration decision:

- user-facing use case and production entry point
- credential source and trusted authorization policy
- spend owner, budget enforcement, current Python billing behavior, and the team wallet that should own Go spend
- API shape and model as one pair, provider, streaming, tools, and structured output
- distinct ID, trace, product, team, and custom attribution
- retry, timeout, fallback, and error behavior
- deployment and egress changes needed to activate and roll back the route

Do not infer requirements from a product name. Read the call and its configuration.

Check model and API shape together. Python can expose an Anthropic model through OpenAI Chat Completions, while Go's native routes do not generally cross-translate shapes. A migration may need both a gateway change and an SDK-shape change.

Separate billing identity from event attribution. Go debits the credential's team. A caller-supplied `team_id` or `ai_product` property can preserve reporting context but cannot select the wallet.

## Classify readiness

Match the inventory to the parity record and current Go implementation:

- ✅ **Ready:** required contracts are supported and the remaining work is client, test, or deployment wiring.
- 🔎 **Verify:** support probably exists, but model availability, wire behavior, billing, attribution, or deployment configuration needs a targeted check.
- ⛔ **Blocked:** migration would lose a required auth, policy, billing, provider, API, or attribution contract.
- 🚧 **In progress:** an open or recently merged PR already owns the migration.

Name the exact evidence for every status. An existing Python helper is migration effort, not a blocker. An `ai_product` property is telemetry, not trusted identity or billing policy.

Python's unbilled flag is not a blocker when an internal workload should debit a PostHog-owned team wallet for spend attribution. Verify that the Go credential resolves to that team. Treat billing as blocked only when migration would charge a customer incorrectly, lose required customer budget policy, or violate a requirement to debit no wallet.

Use ✅ when the production entry point, worker or process, intended paying team, model and API pair, attribution conversion, and rollback path are supported by evidence. The token itself may still need to be created and wired. Use 🔎 when the spend owner, required policy, runtime behavior, or another migration contract is unknown.

## Rank the shortlist

Prioritize candidates that:

1. Have no ⛔ contract.
2. Use a shared Go-capable builder or a stock SDK with a simple base URL change.
3. Already use a Go-supported model, provider, and API shape.
4. Need informational attribution rather than trusted product identity.
5. Can use a customer wallet intentionally or a PostHog-owned wallet for internal spend.
6. Have a narrow deployment boundary, explicit fallback, and cheap verification path.

Lower the rank for broad shared-process switches, unverified billing changes, cross-repository deployment work, or missing production tests. Do not rank by code size alone.

## Report candidates

Return a small decision-oriented table with:

| Candidate | Readiness | Why | Required work | Evidence gaps |
| --------- | --------- | --- | ------------- | ------------- |

List the strongest ready candidate first. Name the exact production process and deployment for each candidate. For blocked callers, state the missing Go contract and where it was verified. For in-progress work, link the existing PR instead of proposing duplicate work. For 🔎 candidates, state the one check that would promote or reject them.

Do not modify callers while running this skill. Once a candidate is selected, run `/migrating-llm-gateway-callers` for that caller.
