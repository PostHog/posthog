# Design — llm-gateway integration as billing source of truth

**Status:** draft. **Owner:** ben.

The agent platform already routes through PostHog's [llm-gateway](https://github.com/PostHog/llm-gateway)
when `useLlmGateway=true` is set on the runner. Today the gateway is a
pass-through proxy with concurrency control via P90 holds, but it does
not yet debit the prepaid wallet on completion. Settlement is landing
in [llm-gateway#43](https://github.com/PostHog/llm-gateway/pull/43)
(`brandon/settle-real-spend`). This plan covers what the agent
platform needs to build to integrate against the post-#43 gateway and
treat it as the source of truth for budget.

Out of scope: per-end-user budgeting (gateway only knows about team
wallets; per-user policy is a follow-up that depends on the gateway's
first-party `phx_`/`pha_` auth plus a `billing_mode`/credential-policy
projection — see open question #5).

## 1. Problem

Today the gateway path on the agent platform is a half-circuit:

- The runner posts to `/v1/chat/completions` with bearer auth
  ([services/agent-runner/src/models/llm-gateway-model.ts](../../../services/agent-runner/src/models/llm-gateway-model.ts)),
  but the bearer comes from `POSTHOG_LLM_GATEWAY_KEY` — a single
  process-wide env var. There's no per-team `phc_` resolution.
- `useGatewayCost: true` zeroes pi-ai's client-side cost numbers in
  `usage_total` ([services/agent-shared/src/spec/usage.ts](../../../services/agent-shared/src/spec/usage.ts)),
  on the assumption that the gateway is authoritative — but the
  gateway doesn't actually debit yet (it calls `Cancel` on every
  completion, never `Settle`). Net: cost is invisible on both sides.
- The runner emits its own `$ai_generation` per turn
  ([platform-llm-analytics.md](platform-llm-analytics.md)). The gateway
  also emits `$ai_generation` on the gateway path. Double-counting in
  AI Analytics is currently masked by the env var staying off in
  shared environments.
- No outbound `X-PostHog-Distinct-Id`, no `Idempotency-Key`, no
  `X-PostHog-Trace-Id`. The gateway gets none of the runner's
  identifying context.
- No handler for HTTP 402. A wallet-empty error today bubbles up as
  generic `pi.stream.failed` and the session goes to `state: failed,
reason: <gateway error message>`.

Once [llm-gateway#43](https://github.com/PostHog/llm-gateway/pull/43)
lands, every streaming request actually decrements the team's
prepaid balance. A team at $0 will 402 immediately on admission. The
runner must be ready to handle that cleanly **before** we flip
`useLlmGateway=true` in any environment carrying real traffic.

## 2. What "integration done" precisely means

Done = a runner-driven session can:

1. Authenticate as the agent's owning team without process-wide config.
2. Stamp identifying headers so gateway-emitted events attribute
   correctly to the agent's session / user / trace.
3. Recover gracefully from a 402 (wallet empty), 429 (rate-limited),
   and `kill_switch` 402.
4. Surface "agent has $X budget remaining" to the agent console and
   refuse to start a session if the wallet can't cover a reasonable
   minimum hold.
5. Eventually stop double-emitting `$ai_generation` — runner owns tool
   spans, gateway owns generation, the two events chain via shared
   trace ID.

The cleanest order is auth + headers + 402 first, then balance
introspection, then dedup. Cost-back is gated on the gateway adding
either a response trailer or a final SSE event — out of scope for
this plan, tracked as a gateway-side dependency.

## 3. Work breakdown

### W1. `phc_` resolver

The runner needs the owning team's project key per session. The token
is on `posthog_team.api_token` (a `phc_...` value).

New helper in [services/agent-shared/src/runtime/](../../../services/agent-shared/src/runtime/):

```typescript
export interface TeamApiKeyResolver {
  /** Returns the team's phc_ project key, throwing if not found / revoked. */
  resolve(teamId: number): Promise<string>
}

export class PgTeamApiKeyResolver implements TeamApiKeyResolver {
  private cache = new Map<number, { value: string; expires: number }>()
  constructor(
    private readonly pool: Pool,
    private readonly ttlMs = 5 * 60_000
  ) {}
  async resolve(teamId: number): Promise<string> {
    const cached = this.cache.get(teamId)
    if (cached && cached.expires > Date.now()) {
      return cached.value
    }
    const { rows } = await this.pool.query<{ api_token: string }>('SELECT api_token FROM posthog_team WHERE id = $1', [
      teamId,
    ])
    if (rows.length === 0 || !rows[0].api_token) {
      throw new Error(`no api_token for team_id=${teamId}`)
    }
    const value = rows[0].api_token
    this.cache.set(teamId, { value, expires: Date.now() + this.ttlMs })
    return value
  }
}
```

Cache TTL keeps the read off the hot path. Tokens rarely rotate;
5min staleness is fine. Wire into `Worker` as a constructor dep
alongside `resolveSecrets` / `resolveIntegrations`. Faux in tests.

The runner only ever calls `resolve(session.team_id)` — there's no
ambient identity to leak across teams.

### W2. Plumb custom headers through pi-client

pi-ai's `SimpleStreamOptions` already accepts `headers?: Record<string, string>`
(node_modules/.pnpm/@earendil-works+pi-ai/dist/types.d.ts:113). The
runner's `InvokeOpts` doesn't surface it
([services/agent-runner/src/models/pi-client.ts:58-72](../../../services/agent-runner/src/models/pi-client.ts#L58-L72)).

One-line additions:

```typescript
export interface InvokeOpts {
  // ...existing...
  headers?: Record<string, string>
}

// in PiAiClient.stream():
const streamOpts: SimpleStreamOptions = {
  // ...existing...
  headers: opts?.headers,
}
```

### W3. Per-call header stamping in run-turn

When the resolved model is gateway-routed, build a header bag per turn:

```typescript
const gatewayHeaders: Record<string, string> = useLlmGateway
  ? {
      'X-PostHog-Distinct-Id': analyticsDistinctId(session),
      'Idempotency-Key': `agent:${session.id}:${turns}`,
      'X-PostHog-Trace-Id': session.id,
    }
  : {}
```

The `apiKey` slot continues to carry the team's `phc_` (pi-ai puts it
in `Authorization: Bearer ...`). The agent platform's analytics
distinct-id strategy already matches what the gateway labels its own
events with ([platform-llm-analytics.md §4](platform-llm-analytics.md)),
so no new mapping needed.

Idempotency key format: `agent:<session.id>:<turn>`. The gateway
dedupes within 24h; runner retries within a turn collapse on the same
key, runner across-turn retries (incrementing `turn`) generate fresh
keys. The format is stable per logical operation, which matches the
gateway's documented expectation.

### W4. 402 + gateway-error handling

pi-ai's openai-completions provider throws on non-2xx. We need to
inspect the error before the runner classifies the session as
`failed`.

Concretely, in [run-turn.ts:305-338](../../../services/agent-runner/src/loop/run-turn.ts#L305-L338),
the catch block currently returns `{ state: 'failed', reason: e.message }`.
Add a classifier:

```typescript
function classifyGatewayError(err: Error): RunOutcome | null {
  const status = extractHttpStatus(err) // pi-ai exposes this via err.cause or err.message
  if (status === 402) {
    return { state: 'failed', reason: 'gateway_insufficient_credits', turns }
  }
  if (status === 429) {
    return { state: 'suspended', reason: 'gateway_throttled', turns }
  }
  return null // fall through to existing handling
}
```

402 is terminal-fail (with a distinct reason so the agent console
shows "out of credits", not "model error"). 429 is suspendable —
the rate-limit window will clear and the janitor's existing requeue
path picks it back up.

The kill-switch case also returns 402 with `code: insufficient_credits`
in the gateway envelope. We treat it identically to wallet-empty for
v0; surfacing "wallet vs kill switch" needs the introspection endpoint
from W5.

### W5. Wallet introspection client + start-up check

Add a small gateway client in agent-shared:

```typescript
export interface WalletClient {
  getBalance(teamId: number): Promise<WalletBalance>
}

export interface WalletBalance {
  available_usd: number
  pending_usd: number
  kill_switch: boolean
}
```

Endpoint: `GET <gatewayBaseUrl>/v1/wallet/balance` (does not exist
gateway-side yet — see open q #1).

Two consumers:

1. **Session start-up gate.** At session claim, the runner calls
   `wallet.getBalance(team_id)`. If `available_usd < MIN_SESSION_HOLD`
   (env-tuned, default $0.50), refuse to claim — emit
   `agent_session_capacity_rejected` with reason `wallet_empty`. This
   pre-empts the per-turn 402 noise.

2. **Agent console UI.** A new
   `agent-applications-wallet-balance` MCP tool / REST endpoint on the
   janitor returns balance for the agent's owner team so the console
   can show "$X remaining" alongside the agent.

For v0, the client can degrade gracefully when the endpoint doesn't
exist: a 404 means "introspection unavailable, skip the start-up
gate, rely on per-turn 402 fallback". Don't fail-closed during the
window where #43 has landed but the balance endpoint hasn't.

### W6. Pricing snapshot + cost recomputation (deferred)

The runner zeroes cost on the gateway path because pi-ai's client-side
numbers are wrong and the gateway hasn't returned anything authoritative.

Two paths once the gateway is settling:

- **Option A.** Gateway adds a final SSE event with cost (per the
  cross-reference findings on the gateway side; no PR yet). Runner
  reads it, persists in `usage_total`, flips `useGatewayCost` to mean
  "trust this number, not pi-ai's". Best long-term.

- **Option B.** Runner ships its own pricing snapshot (sync'd from
  the same `llm-costs.json` the gateway uses). Recomputes cost from
  the trusted token counts. No gateway round trip. Per-turn-cost-capture.md
  §7.3 already chose this as option (1).

Both are out of scope for this plan; pick after #43 + cost-back-to-caller
clarify. The runner stays on `useGatewayCost: true` (cost zeroed
in `usage_total`) until then. Note: gateway-emitted `$ai_generation`
events DO carry cost — so the truth is queryable from LLM Analytics
even while the session row's cost stays blank.

### W7. Analytics emission de-duplication (deferred)

Both sides currently emit `$ai_generation`. For gateway-routed turns
this double-counts. The clean solution is:

- Runner suppresses its own `$ai_generation` when `useLlmGateway=true`.
- Runner still emits `$ai_span` for tool calls (gateway can't see tools).
- Tool spans chain to the gateway's generation via shared
  `$ai_trace_id` (= `session.id`) and via the gateway echoing
  `request_id` back so the runner can stamp it as `$ai_parent_id`.

The "gateway echoes request_id back to caller" piece needs gateway-side
work (response header, e.g. `X-PostHog-Request-Id`, would do it). Until
that lands, the spans still chain by trace but not by parent — that's
adequate for v0 dashboards.

Suppression is a 3-line change in [run-turn.ts:371](../../../services/agent-runner/src/loop/run-turn.ts#L371)
guarded on `deps.useGatewayCost`. Ship it after the dedupe story is
agreed cross-team.

## 4. Open questions

1. **Wallet introspection endpoint shape.** The gateway team hasn't
   built `GET /v1/wallet/balance` yet (called out as deferred in
   PR #43's "Known gaps"). Agree on:
   - Path: `GET /v1/wallet/balance` (no team_id in path — auth identifies it).
   - Auth: same `Authorization: Bearer phc_` as the data plane.
   - Response: `{ available_usd, pending_usd, kill_switch, currency: 'USD' }`.

   Without it, W5's start-up gate degrades to "skip, fall through to
   per-turn 402". Acceptable for v0, ugly for the agent console.

2. **402 → suspended or failed?** This plan treats 402 as terminal
   (`failed: gateway_insufficient_credits`). Alternative: park in
   `suspended` and auto-resume when a topup happens. Resume signal
   would need a billing-side webhook → janitor → enqueue. Not in
   v0; document the eventual shape if we go there.

3. **Idempotency-Key collision across retries.** Runner janitor's
   stuck-running reaper requeues a session ([rate-limiting-sessions.md §10.8](rate-limiting-sessions.md#10-open-questions))
   — the next turn re-runs with the same `(session.id, turn)`
   coordinates. That collapses on the gateway dedupe and replays the
   original response. Is that what we want? Probably yes — a stuck
   session shouldn't double-bill. But the runner sees the dedupe
   transparently, so debug-side it looks like "the turn just ran
   again with the same output". Worth a log line.

4. **Cost-back format if/when the gateway adds it.** Strong preference
   for a final SSE event over a response header — pi-ai surfaces SSE
   events to its consumers but doesn't expose response headers. The
   gateway's PR #43 already injects `stream_options.include_usage`
   per-request for OpenAI; piggy-backing one more synthetic event is
   cheap. Coordinate with the gateway team before they design it.

5. **Per-user budget (the original framing).** Punted. Gateway today
   has team-wallet only; per-user budgeting is its own design that
   layers on the gateway's first-party `phx_`/`pha_` auth plus a
   per-credential `billing_mode` policy. Once team-wallet integration
   is working end-to-end, evaluate whether per-user budgeting belongs
   in:
   - The gateway (extend admission), or
   - The agent platform (read per-user usage_total totals and enforce
     before claiming a session).

   The gateway path is cleaner architecturally (admission-control is
   its job) but requires gateway changes including a new Redis axis
   per `(team_id, distinct_id)`. The agent platform path is fully
   self-contained and could ship without gateway changes. Lean toward
   the latter for v1 — usage_total per principal is already cheap
   to query with the existing column.

## 4a. Verifying integration

A go-button smoke script lives at
[services/agent-runner/bin/gateway-smoke.ts](../../../services/agent-runner/bin/gateway-smoke.ts)
with two modes:

```bash
# Talk to a running gateway with a real team's phc_:
POSTHOG_DB_URL=postgres://... \
POSTHOG_LLM_GATEWAY_URL=http://localhost:8080/v1 \
TEAM_ID=1 \
pnpm --filter=@posthog/agent-runner gateway:smoke probe

# Run a fake gateway that logs incoming headers + replies with a status of
# your choosing (great for verifying the runner's wire shape without booting
# a real gateway):
ECHO_STATUS=402 pnpm --filter=@posthog/agent-runner gateway:smoke echo
```

`probe` does what the runner does end-to-end: resolves the team's `phc_`,
builds the same header bag + chat-completion body, posts to the gateway,
and routes the response through the same `classifyGatewayError` the runner
uses. Reports PASS/FAIL with the exact runner-side outcome for each
classifier branch (200, 401, 402, 429, 5xx).

`echo` mimics the gateway: serves a stub OpenAI streaming SSE body on 200,
or the gateway's JSON envelope shape on 4xx/5xx. Point the runner at it
via `POSTHOG_LLM_GATEWAY_URL=http://localhost:8765/v1
AGENT_USE_LLM_GATEWAY=true` to exercise the full runner loop against
arbitrary gateway responses without standing up the real gateway.

## 5. Rollout

**v0 — auth + headers + 402** (this plan's first PR-sized chunk):

- W1: `PgTeamApiKeyResolver` + cache.
- W2: `InvokeOpts.headers` plumbed through pi-client.
- W3: header stamping in run-turn for the gateway path.
- W4: 402/429 classifier with distinct session reasons.
- Tests: faux gateway returning 402, 429, 200 with verification that
  outbound headers carry the expected values.
- Behaviour change: `useLlmGateway=true` becomes safe to flip on a
  shared environment with funded team wallets. Pre-#43 it's a no-op
  on billing; post-#43 the wallets actually decrement.

**v1 — wallet introspection**:

- W5: `WalletClient` + start-up gate + agent-console balance display.
- Depends on the gateway's `GET /v1/wallet/balance` endpoint.

**v2 — cost truth + dedup**:

- W6: pricing snapshot OR final-SSE cost ingestion. Pick once the
  gateway team commits to one.
- W7: runner-side `$ai_generation` suppression on the gateway path.
- Cross-team agreement on trace/parent-span linkage.

**v3+ — per-user budgets**: separate plan once team-wallet is solid.

## 6. Dependencies + what this enables

**Depends on:**

- [llm-gateway#43](https://github.com/PostHog/llm-gateway/pull/43)
  landing for any real budget enforcement.
- [llm-gateway#42](https://github.com/PostHog/llm-gateway/pull/42) +
  [llm-gateway#39](https://github.com/PostHog/llm-gateway/pull/39) as
  #43's stack.
- Gateway-side `GET /v1/wallet/balance` for W5 (no PR yet).
- Gateway-side cost-back-to-caller for W6 (no PR yet).

**Composes with:**

- [per-turn-cost-capture.md](per-turn-cost-capture.md) — once W6
  lands, `usage_total.cost_*` on the session row stops being zero for
  gateway-routed sessions.
- [platform-llm-analytics.md](platform-llm-analytics.md) — W7
  resolves the runner/gateway double-emit by shifting generation
  emission to the gateway for the gateway path.
- [rate-limiting-sessions.md](rate-limiting-sessions.md) — W5's
  start-up gate is a cost-axis admission check that complements the
  concurrency-axis one already in that plan.

**Enables / interacts with:**

- A future per-user budget plan (open q #5).
- The agent console's "spend this month" surface (hinted in
  [_ROADMAP.md] item B.3 / per-turn-cost-capture §5).
- Cost-based session refusal as a defense against runaway loops
  cheaper than wall-clock max_turns alone.
