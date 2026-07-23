# Testing the LLM step against the new ai-gateway (local)

This branch points the CDP LLM executor at the new Go **ai-gateway**
([PostHog/ai-gateway](https://github.com/PostHog/ai-gateway)) instead of the old Python gateway. The
executor calls `POST /v1/chat/completions` (OpenAI shape, non-streaming), which the new gateway
serves as a true-proxy — so the client contract is unchanged; only the endpoint it points at moves.

## 1. Run the ai-gateway

In a clone of `PostHog/ai-gateway`:

```bash
just setup     # copies .env.example -> .env (first run)
# set provider keys + open auth in .env:
#   AI_GATEWAY_OPENAI_API_KEY=sk-...
#   AI_GATEWAY_ANTHROPIC_API_KEY=sk-ant-...
#   AI_GATEWAY_AUTH_MODE=open      # dev: anonymous principal, accepts any bearer
just dev       # deps-up (Postgres + Valkey) + seed test team + run gateway on :8080
```

Its Postgres/Valkey ports are shifted off 5432/6379, so it runs alongside the `posthog/posthog`
stack without colliding. Smoke test:

```bash
curl -N -H 'Content-Type: application/json' \
  -d '{"model":"gpt-5.4-mini","messages":[{"role":"user","content":"hi"}]}' \
  localhost:8080/v1/chat/completions
```

## 2. Point the CDP executor at it

In the `posthog/posthog` stack env:

```bash
CDP_LLM_GATEWAY_URL=http://localhost:8080
CDP_LLM_GATEWAY_TOKEN=anything          # ignored under AI_GATEWAY_AUTH_MODE=open
```

The `cdp-llm-executor` capability is on by default in dev.

## 3. Model ids

The new gateway resolves a fixed catalog. Use one of:
`gpt-5.4-mini`, `gpt-4o`, `claude-sonnet-4.6`, `claude-haiku-4.5`, `claude-opus-4.8`.
The AI step defaults to `gpt-5.4-mini`. Other ids (e.g. `gpt-5-mini`) 400 at the gateway.

## Contract notes (why the client works unchanged)

- **Headers are recognized as-is**: `Authorization: Bearer`, `Idempotency-Key` (dedupe →
  `$ai_gateway_idempotency_key`), `X-PostHog-Trace-Id` (→ `$ai_trace_id`), and `X-PostHog-Properties`
  (merged onto `$ai_generation`; this branch sends `hog_flow_id` + `action_id`).
- **Team comes from the bearer**, not a header — under `resolver` auth a team-scoped `phs_`
  (`llm_gateway:read`) identifies the team whose prepaid wallet is charged; under `open` auth the
  principal is anonymous.
- **Billing** is the gateway's prepaid wallet / Postgres ledger (admission reserves cost before
  dispatch, settles on stream close). `$ai_generation` is analytics only.
- **Errors**: 402 (wallet exhausted) and other 4xx are terminal → error branch; 429 (with
  `Retry-After`) and 5xx are retriable → in-fleet defer/retry.
