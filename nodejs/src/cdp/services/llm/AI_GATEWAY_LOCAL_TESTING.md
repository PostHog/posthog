# Testing the LLM step against the new ai-gateway (local)

This branch points the CDP LLM executor at the new Go **ai-gateway**
([PostHog/ai-gateway](https://github.com/PostHog/ai-gateway)) instead of the old Python gateway. The
executor calls `POST /v1/chat/completions` (OpenAI shape, non-streaming), which the new gateway
serves as a true-proxy — so the client contract is unchanged; only the endpoint it points at moves.

## 1. Run the ai-gateway

In a clone of `PostHog/ai-gateway`:

```bash
just setup     # copies .env.example -> .env (first run)
# in .env set provider keys + resolver auth:
#   AI_GATEWAY_OPENAI_API_KEY=sk-...
#   AI_GATEWAY_ANTHROPIC_API_KEY=sk-ant-...
#   AI_GATEWAY_AUTH_MODE=resolver     # use resolver, NOT open — see the auth note below
just dev       # deps-up (Postgres + Valkey) + seed test team + run gateway on :8080
```

`just dev` seeds **team 42**, funded with $100, reachable with the bearer token **`phs_livesmoke`**.
Its Postgres/Valkey ports are shifted off 5432/6379, so it runs alongside the `posthog/posthog`
stack without colliding. Smoke test (bearer required under resolver auth):

```bash
curl -N -H 'Content-Type: application/json' -H 'Authorization: Bearer phs_livesmoke' \
  -d '{"model":"gpt-5.4-mini","messages":[{"role":"user","content":"hi"}]}' \
  localhost:8080/v1/chat/completions
```

### Auth note — do not use `AI_GATEWAY_AUTH_MODE=open`

Open auth resolves every call to an anonymous principal (`team_id = 0`). Admission floors spend at
`balance + overspend_allowance`, and both are forced to 0 for the anonymous principal, so **every
request 402s with `insufficient_credits`** and there's no supported way to fund team 0. Use
`resolver` mode with the seeded `phs_livesmoke` / team 42 above — that is the working local path (it
does draw down team 42's wallet, which is the point: it exercises admission + billing, not just
dispatch).

## 2. Point the CDP executor at it

In the `posthog/posthog` stack env:

```bash
CDP_LLM_GATEWAY_URL=http://localhost:8080
CDP_LLM_GATEWAY_TOKEN=phs_livesmoke     # the seeded team-42 bearer
```

The `cdp-llm-executor` capability is on by default in dev.

## 3. Model ids

Use an **OpenAI** model locally — those dispatch: `gpt-5.4-mini` (the AI step default), `gpt-4o`,
`gpt-4o-mini`. Anthropic ids resolve in the catalog but currently return `router rejected request`
in local dev, so don't rely on them here. Anthropic ids are also **hyphenated** in the catalog
(`claude-haiku-4-5`, `claude-sonnet-4-6`), not dotted. The authoritative live catalog is
`GET /v1/models`.

## 4. Verifying `$ai_generation` attribution (optional)

By default in dev the gateway logs `$ai_generation` to its slog only and does **not** emit it to
capture (it won't emit unsigned billing events). To assert the branch's attribution — the
`X-PostHog-Properties` merge (`hog_flow_id`, `action_id`) and `$ai_trace_id = job id` — as a real
captured event, set `AI_GATEWAY_SIGNING_SECRET` in the gateway's `.env` so it emits to capture.
Otherwise, confirm the values in the gateway slog.

## Contract notes (why the client works unchanged)

- **Headers are recognized as-is**: `Authorization: Bearer`, `Idempotency-Key` (dedupe →
  `$ai_gateway_idempotency_key`), `X-PostHog-Trace-Id` (→ `$ai_trace_id`), and `X-PostHog-Properties`
  (merged onto `$ai_generation`; this branch sends `hog_flow_id` + `action_id`).
- **Team comes from the bearer**, not a header — a team-scoped `phs_` (`llm_gateway:read`) identifies
  the team whose prepaid wallet is charged. Locally that's `phs_livesmoke` → team 42.
- **Billing** is the gateway's prepaid wallet / Postgres ledger (admission reserves cost before
  dispatch, settles on stream close). `$ai_generation` is analytics only.
- **Errors**: 402 (wallet exhausted) and other 4xx are terminal → error branch; 429 (with
  `Retry-After`) and 5xx are retriable → in-fleet defer/retry.
