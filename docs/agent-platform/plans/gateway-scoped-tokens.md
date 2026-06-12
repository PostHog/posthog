# Proposal — native scoped tokens in the ai-gateway

**Status:** proposal (resolves open q #6 of `agent-sandbox-tiers.md` long-term). **Owner:** ben.

The agent platform just shipped a session-scoped inference proxy on ingress
(`/inference/v1/*`): the tier-2 coding sandbox holds a session capability token,
the proxy holds the real gateway key, swaps it in, and checks session liveness.
That was the right v0 — no upstream dependency, shipped in a day. This doc
proposes the long-term home: the **gateway natively issues short-lived,
spend-capped, header-pinned tokens**, and the platform proxy retires.

## Why it makes sense

1. **The need is not platform-specific.** The tasks product puts a real
   `phx_` in its sandboxes today; any future untrusted caller (playgrounds,
   user-facing SDK surfaces, MCP clients) has the identical problem. One
   gateway feature beats N per-product proxies.
2. **Spend enforcement belongs where the ledger is.** The gateway already has
   the prepaid wallet, P90 admission holds, and settlement
   (`internal/quota/quota.go:75` `Admit`, `:107` `Settle`; `internal/ledger/`).
   Our proxy can check _liveness_ but cannot meter _dollars_ without
   duplicating the wallet. A per-token max-spend is a sub-budget on
   infrastructure that already exists.
3. **The auth seam is ready.** `Authenticator` is an interface
   (`internal/auth/auth.go:22`), `Principal` is the single carrier struct every
   downstream stage reads (`internal/principal/principal.go:7`), and RFC #1103
   already plans scoped first-party credentials (`phx_`/`pha_` with
   per-credential scope — TODOs at `internal/auth/resolver.go:17`,
   `internal/principal/principal.go:34`). Derived tokens are a natural sibling.
4. **Removes a hop we must keep correct** — SSE pass-through, long-stream
   timeouts, big request bodies. The proxy is ~150 lines but it's load-bearing
   streaming code on the inference hot path.
5. **Prior art:** LiteLLM virtual keys — same shape, well understood.

## What it would look like (gateway side)

### Issuance

```text
POST /v1/tokens            (auth: real credential — phc_/phx_)
{
  "ttl_seconds": 1500,
  "max_spend_usd": "2.50",
  "allow_models": ["anthropic/claude-sonnet-4.6"],      // optional narrow
  "pinned": {                                            // optional, wins over caller headers
    "distinct_id": "coding-<session-id>",
    "trace_id": "<session-id>",
    "properties": { "$ai_session_id": "<session-id>" }
  },
  "label": "agent-platform session <id>"
}
→ { "token": "phs_...", "id": "...", "expires_at": "..." }

DELETE /v1/tokens/{id}     (auth: issuer credential) → instant revocation
```

- **Opaque token + Redis record**, not a stateless JWT: the gateway is already
  Redis-native (session holds, idempotency dedupe — mature TTL'd-state
  patterns in `internal/session/`), the record is the natural home for the
  live spend counter, and revocation is a key delete instead of a denylist.
  Redis TTL = token expiry; nothing to GC.

### Resolution

- New prefix `phs_` → a `ScopedTokenResolver` implementing `Authenticator`,
  coexisting with the hypercache resolver (auth is already pluggable).
- Builds a `Principal` inheriting `TeamID` from the issuer, with new fields:
  `MaxSpendUSD` + token id (for the spend counter), `Pinned` (distinct id /
  trace id / properties — **pinned values override caller headers**, so the
  untrusted holder cannot spoof attribution), `AllowList` = team allowlist ∩
  token `allow_models`.

### Enforcement

- `quota.Admit` gains one check: atomic `spent + p90_hold ≤ max_spend` on the
  token's Redis record (same Lua pattern as today's concurrent-session
  holds). Over budget → the existing 402 envelope.
- `quota.Settle` adds actual cost to the token's spent counter alongside the
  team-ledger debit it already does.
- `emitter` stamps the token id/label on `$ai_generation` so per-session
  spend is attributable in LLM analytics.

Everything lands inside existing module boundaries — auth (new resolver),
principal (new fields), quota (one check per Admit/Settle), emitter (one
field). No architectural refactor.

## What the agent platform side becomes

- `coding-driver` at sandbox acquisition: `POST /v1/tokens`
  (ttl = wall limit + slack, `max_spend` = session budget, pinned ids =
  session id) → hand the `phs_` token to the harness; `LLM_GATEWAY_URL`
  points at the gateway directly.
- Session stop/cancel/complete → `DELETE /v1/tokens/{id}`. Strictly better
  than today's liveness check: revocation also stops in-flight admission, and
  the budget cap bounds the damage even if the revoke is missed.
- The ingress `/inference` proxy retires (or stays as a one-release shim).
  The runner's `codingGateway.inferenceProxy` seam stays — only the mint
  swaps from `mintInferenceProxyToken` to the gateway API.
- This also gives the per-session **budget** the platform proxy couldn't:
  open q #2's token-spend axis gets enforced at the gateway choke point with
  no spec→proxy budget plumbing on our side.

## What the proxy still does that the gateway can't

Session liveness ("is this session row `running`?") is platform state the
gateway shouldn't know about. The replacement posture is: short TTL +
`max_spend` + explicit revoke on every terminal transition. That bounds a
leaked/stale token by dollars and minutes instead of by state, which is the
more meaningful bound anyway.

## Sequencing

1. Keep the shipped ingress proxy — it's correct, tested, and unblocks v0.
2. Land this as a gateway RFC (it slots beside #1103; the issuance endpoint
   doesn't depend on `phx_`/`pha_` landing first — issuer auth can start as
   `phc_`-only).
3. When `phs_` exists, swap the runner's mint + retire the proxy route.
4. Tasks product migrates off real-`phx_`-in-sandbox onto the same tokens —
   the convergence dividend.
