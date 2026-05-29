# AI gateway introspection — billing read plane + console Billing tab

Add a read-only introspection surface (wallet + ledger) for the AI gateway,
hosted on `cmd/billing`, surfaced in agent-console via Django proxy.

Companion to [`ai-gateway-integration.md`](./ai-gateway-integration.md) (W5/W6).
Runner path is **untouched** — runner still talks only to `cmd/gateway` with
`phc_` for `/v1/usage/{request_id}` and `/v1/wallet/balance`.

## Architecture

```text
console ─→ Django ─→ ai-gateway/billing ─→ (postgres ledger, redis pending)
                          ↑
              x-internal-secret header
runner ──→ ai-gateway/gateway (phc_)  ← unchanged
```

## Branches

- `posthog`: commit direct to `ass` (current branch)
- `ai-gateway`: commit direct to `feat/usage-and-wallet-endpoints`

## Endpoint split (final)

| Endpoint                         | Service                         | Auth                | Consumer                               |
| -------------------------------- | ------------------------------- | ------------------- | -------------------------------------- |
| `POST /v1/messages` etc.         | gateway                         | `phc_`              | customer SDK                           |
| `GET /v1/usage/{request_id}`     | gateway, **unchanged**          | `phc_`              | runner                                 |
| `GET /v1/wallet/balance`         | gateway, **unchanged** (narrow) | `phc_`              | runner (start-of-session credit check) |
| `GET /v1/wallet` (new, extended) | **billing**                     | `x-internal-secret` | Django → console                       |
| `GET /v1/ledger` (new)           | **billing**                     | `x-internal-secret` | Django → console                       |

---

## Part A — ai-gateway repo

Branch: `feat/usage-and-wallet-endpoints`.

### A1. Internal-secret middleware

**File:** `internal/httpapi/internal_auth.go` (new)

```go
func internalSecretRequired(expected string) func(http.Handler) http.Handler
```

Constant-time compare on `x-internal-secret` header. 401 on mismatch (use existing
`WriteError` helper, `CodeAuthFailed`). Apply to a route group, not per-handler.

### A2. Config

**File:** `internal/config/config.go`

Add to billing-role config:

```go
BillingInternalSecret string // env AI_GATEWAY_BILLING_INTERNAL_SECRET
```

Required when role=billing — fail boot if empty (matches the existing
`ALLOW_OPEN_AUTH` loud-on-misconfig pattern).

Update `internal/config/config_test.go` defaults + role gating tests.

### A3. Extend `ledger.Recent` with keyset pagination + filters

**File:** `internal/ledger/ledger.go`

```go
type RecentOpts struct {
    Limit             int               // default 50, max 200
    Cursor            *Cursor           // nil = first page
    TransactionType   *TransactionType  // nil = all
    ReferenceIDPrefix *string           // nil = all (e.g. "agent:<session_id>:")
}

type Cursor struct {
    CreatedAt time.Time
    ID        string
}

// Update existing Recent signature
func (s *Store) Recent(ctx context.Context, teamID int64, opts RecentOpts) ([]Entry, *Cursor, error)
```

SQL: keyset on `(created_at desc, id desc)`. Add `where (created_at, id) < ($cursor_at, $cursor_id)`
when cursor present; `where transaction_type = $tt` / `where reference_id like $prefix || '%'`
when present. The existing `ledger_entries_team_created_idx` already covers the keyset path.
The `LIKE 'agent:%' || '%'` prefix scan needs no new index at v0 row counts; revisit if hot.

Return the next cursor as `&Cursor{CreatedAt: last.CreatedAt, ID: last.ID}` when results
== limit, nil otherwise.

Test against the existing `internal/ledger/integration_test.go` Postgres harness.

### A4. New wallet handler (extended shape)

**File:** `internal/httpapi/wallet.go` (new — split off from `usage.go`)

```go
type AccountLookup interface {
    Account(ctx context.Context, teamID int64) (ledger.Account, error)
}

// Optional. Soft-fail to tripped=false + omit rolling_hour_usd if nil/errors.
type KillSwitchLookup interface {
    State(ctx context.Context, teamID int64) (KillSwitchState, error)
}

type KillSwitchState struct {
    Tripped      bool
    ThresholdUSD *decimal.Decimal
    TrippedAt    *time.Time
    RollingHour  *decimal.Decimal
}

type walletResponse struct {
    TeamID         int64             `json:"team_id"`
    AvailableUSD   string            `json:"available_usd"`     // balance - pending
    PendingUSD     string            `json:"pending_usd"`
    BalanceUSD     string            `json:"balance_usd"`       // raw ledger balance
    SpendableUSD   string            `json:"spendable_usd"`     // balance + overage_allowance
    Currency       string            `json:"currency"`
    Account        accountSummary    `json:"account"`
    RollingHourUSD *string           `json:"rolling_hour_usd,omitempty"`
    KillSwitch     killSwitchSummary `json:"kill_switch"`
}

type accountSummary struct {
    Profile             string  `json:"profile"`          // "A" | "B" | "C"
    OverageAllowanceUSD string  `json:"overage_allowance_usd"`
    Period              string  `json:"period"`
    PeriodAnchor        string  `json:"period_anchor"`    // RFC3339
    RateCardID          *string `json:"rate_card_id,omitempty"`
}

type killSwitchSummary struct {
    Tripped      bool    `json:"tripped"`
    ThresholdUSD *string `json:"threshold_usd,omitempty"`
    TrippedAt    *string `json:"tripped_at,omitempty"`
}
```

`GET /v1/wallet?team_id=42`. Parse `team_id` from query, validate positive int64.
Call `BalanceLookup.Balance`, `PendingLookup.Pending`, `ledger.Store.Spendable`,
`AccountLookup.Account`, optionally `KillSwitchLookup.State`. Sum/format with
`shopspring/decimal`. Soft-fail kill switch + rolling hour to `tripped: false` /
omitted when lookup nil or errors (info log, not warn).

Example response:

```json
{
  "team_id": 42,
  "available_usd": "12.4500",
  "pending_usd": "0.1500",
  "balance_usd": "12.6000",
  "spendable_usd": "12.6000",
  "currency": "USD",
  "account": {
    "profile": "C",
    "overage_allowance_usd": "0.000000",
    "period": "monthly",
    "period_anchor": "2026-05-01T00:00:00Z"
  },
  "kill_switch": { "tripped": false }
}
```

### A5. New ledger handler

**File:** `internal/httpapi/ledger.go` (new)

```go
type LedgerLookup interface {
    Recent(ctx context.Context, teamID int64, opts ledger.RecentOpts) ([]ledger.Entry, *ledger.Cursor, error)
}

type ledgerEntryResponse struct {
    ID              string  `json:"id"`
    TransactionType string  `json:"transaction_type"`
    Source          string  `json:"source"`
    Destination     string  `json:"destination"`
    AmountUSD       string  `json:"amount_usd"`
    ListCostUSD     *string `json:"list_cost_usd,omitempty"`
    ReferenceID     *string `json:"reference_id,omitempty"`
    Model           *string `json:"model,omitempty"`
    Provider        *string `json:"provider,omitempty"`
    InputTokens     *int64  `json:"input_tokens,omitempty"`
    OutputTokens    *int64  `json:"output_tokens,omitempty"`
    DistinctID      *string `json:"distinct_id,omitempty"`
    CreatedAt       string  `json:"created_at"`
}

type ledgerListResponse struct {
    Results    []ledgerEntryResponse `json:"results"`
    NextCursor *string               `json:"next_cursor,omitempty"`
}
```

`GET /v1/ledger?team_id=42&limit=50&cursor=...&transaction_type=debit&reference_id_prefix=agent:<session_id>:`

- `cursor` opaque base64-encoded `<created_at_unix_ns>:<id>`. Reject malformed.
- `limit` default 50, max 200.
- `transaction_type` ∈ {debit, topup, refund, adjustment} or absent.
- `reference_id_prefix` arbitrary string, max 256 chars.

### A6. Routes wiring

**File:** `internal/httpapi/routes.go`

Add to `Deps`:

```go
type Deps struct {
    // ...existing...
    InternalReads *InternalReadDeps // billing wires this; gateway leaves nil
}

type InternalReadDeps struct {
    Secret        string
    Wallet        WalletReadDeps
    LedgerLookup  LedgerLookup
}

type WalletReadDeps struct {
    Balance     BalanceLookup
    Pending     PendingLookup
    Spendable   SpendableLookup
    Account     AccountLookup
    KillSwitch  KillSwitchLookup // optional
}
```

In `New`, when `InternalReads != nil`:

```go
r.Group(func(r chi.Router) {
    r.Use(internalSecretRequired(d.InternalReads.Secret))
    r.Get("/v1/wallet", walletHandler(d.Logger, d.InternalReads.Wallet))
    r.Get("/v1/ledger", ledgerHandler(d.Logger, d.InternalReads.LedgerLookup))
})
```

**Do not touch** the existing data-plane wiring of `UsageLookup` / `WalletBalance` /
`WalletPending` on gateway — those stay exactly as-is for the runner.

### A7. Billing main

**File:** `cmd/billing/main.go`

Wire `InternalReadDeps` using the already-constructed `ledger.NewStore(pool)` and
`session.NewClient(rdb, sessionTTL)`. `KillSwitch` left nil for now (soft-fail path).
Pricing not needed here.

### A8. Smoke / dev

Add a `just` recipe `just smoke-billing-reads` that curls `/v1/wallet?team_id=<seed>`
and `/v1/ledger?team_id=<seed>` against the local billing binary with the dev
shared secret. Useful while iterating; not load-bearing.

### Local dev

Billing already listens on `:8081` (`AI_BILLING_LISTEN_ADDR=:8081` in `.env.example`).
Add `AI_GATEWAY_BILLING_INTERNAL_SECRET=dev-secret-change-me` to `.env.example`.

---

## Part B — posthog repo

Branch: `ass` (current).

### B1. Settings

**File:** `posthog/settings/...` (find the right module — likely `posthog/settings/web.py`
or a dedicated `posthog/settings/ai_gateway.py` if there's a pattern there)

```python
AI_GATEWAY_BILLING_URL = os.getenv("AI_GATEWAY_BILLING_URL", "http://localhost:8081")
AI_GATEWAY_BILLING_INTERNAL_SECRET = os.getenv("AI_GATEWAY_BILLING_INTERNAL_SECRET", "")
```

Empty default for the secret is intentional — view returns 503 when unset so
non-agent-platform devs aren't broken.

### B2. Billing client

**File:** `posthog/ai_gateway/__init__.py` (new), `posthog/ai_gateway/client.py` (new)

```python
class BillingClient:
    def __init__(self, base_url: str, internal_secret: str, timeout: float = 3.0): ...
    def wallet(self, team_id: int) -> dict: ...
    def ledger(
        self,
        team_id: int,
        *,
        limit: int | None = None,
        cursor: str | None = None,
        transaction_type: str | None = None,
        reference_id_prefix: str | None = None,
    ) -> dict: ...
```

Synchronous httpx wrapper. Sets `x-internal-secret` header. No retry loop —
admin reads, not settle-window. Raises `BillingUnavailable` on connection
errors / 5xx; raises `BillingMisconfigured` if `internal_secret` is empty.

### B3. Django viewset

**File:** `posthog/api/ai_gateway.py` (new)

```python
class AIGatewayViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    scope_object = "ai_gateway"  # add to access-control allowlist

    @extend_schema(responses=WalletSerializer)
    @action(detail=False, methods=["get"])
    def wallet(self, request):
        client = self._client_or_503()
        if client is None: return Response(...)
        return Response(client.wallet(self.team.id))

    @extend_schema(responses=LedgerListSerializer, parameters=[...])
    @action(detail=False, methods=["get"])
    def ledger(self, request):
        client = self._client_or_503()
        if client is None: return Response(...)
        opts = LedgerQuerySerializer(data=request.query_params)
        opts.is_valid(raise_exception=True)
        return Response(client.ledger(self.team.id, **opts.validated_data))
```

Serializers:

- `WalletSerializer` — mirrors `walletResponse` shape; **must** annotate every field
  with `help_text` per [improving-drf-endpoints](../../.agents/skills/improving-drf-endpoints.md)
  so generated TS types are useful.
- `LedgerEntrySerializer`, `LedgerListSerializer`, `LedgerQuerySerializer` — same.
- Use `serializers.CharField` for decimal strings (preserve precision); document in `help_text`.

Map billing errors:

- `BillingUnavailable` → 502 `{"error": "billing_unavailable"}`
- `BillingMisconfigured` → 503 `{"error": "ai_gateway_not_configured"}`
- billing 404 (only on `usage`, which we don't expose here) — n/a

### B4. URL wiring

**File:** [`posthog/api/__init__.py`](../../posthog/api/__init__.py)

Register `AIGatewayViewSet` under the projects router. Routes land at:

- `GET /api/projects/<team_id>/ai_gateway/wallet/`
- `GET /api/projects/<team_id>/ai_gateway/ledger/`

### B5. Permissions

`scope_object = "ai_gateway"` — add to wherever scopes are enumerated (search for
existing `scope_object` values to find the registry). Read access requires the
standard team membership check the mixin enforces.

### B6. Janitor walletProxy cleanup (same PR)

**Files:**

- [`services/agent-janitor/src/server.ts`](../../services/agent-janitor/src/server.ts) — delete
  `GET /applications/:application_id/wallet` route, drop `walletProxy` from `JanitorServerOpts`
- [`services/agent-janitor/src/index.ts`](../../services/agent-janitor/src/index.ts) +
  [`config.ts`](../../services/agent-janitor/src/config.ts) — drop env wiring that
  constructed `walletProxy`
- [`products/agent_stack/backend/janitor_client.py`](../../products/agent_stack/backend/janitor_client.py) —
  remove the corresponding Python method
- [`products/agent_stack/backend/api.py`](../../products/agent_stack/backend/api.py) —
  remove any Django-side wiring that called through
- Search `services/agent-console/src/lib/apiClient.ts` for any wallet-via-janitor
  function and delete; the console will use the new ai_gateway endpoint instead

### B7. Generate types

```sh
hogli build:openapi
```

Generated:

- `frontend/src/generated/core/api.schemas.ts` — `Wallet`, `LedgerEntry`,
  `LedgerListResponse` types
- `frontend/src/generated/core/api.ts` + `api.zod.ts`
- Re-run from posthog root, commit generated diff

### B8. Console apiClient

**File:** [`services/agent-console/src/lib/apiClient.ts`](../../services/agent-console/src/lib/apiClient.ts)

```ts
export async function getWallet(teamId: number): Promise<Wallet> {
  return getJson<Wallet>(posthogUrl(teamId, '/ai_gateway/wallet/'))
}

export interface LedgerListOpts {
  limit?: number
  cursor?: string
  transactionType?: 'debit' | 'topup' | 'refund' | 'adjustment'
  referenceIdPrefix?: string
}

export async function listLedger(teamId: number, opts: LedgerListOpts = {}): Promise<LedgerListResponse> {
  const params = new URLSearchParams()
  if (opts.limit) params.set('limit', String(opts.limit))
  if (opts.cursor) params.set('cursor', opts.cursor)
  if (opts.transactionType) params.set('transaction_type', opts.transactionType)
  if (opts.referenceIdPrefix) params.set('reference_id_prefix', opts.referenceIdPrefix)
  const qs = params.toString()
  return getJson<LedgerListResponse>(posthogUrl(teamId, `/ai_gateway/ledger/${qs ? `?${qs}` : ''}`))
}
```

Import types from the generated bundle (per
[`adopting-generated-api-types`](../../.agents/skills/adopting-generated-api-types.md)).

### B9. Console UI — Billing tab

**New route:** `services/agent-console/app/billing/page.tsx` + `billing-client.tsx`

Top-level nav entry "Billing" next to "Agents". Page composition:

```text
┌─ WalletCard ──────────────────────────────────────┐
│ Available  $12.45        Plan: prepaid (C)        │
│ Pending    $0.15         Period: monthly          │
│ Spendable  $12.60        Kill switch: ok          │
│ [Rolling hour: $0.42 / threshold n/a]             │
└───────────────────────────────────────────────────┘

┌─ Ledger feed ─────────────────────────────────────┐
│ [Filter: all / debit / topup / refund / adjustment]│
│ 2026-05-29 14:22  debit   anthropic/claude-...  -$0.0312 │
│ 2026-05-29 14:21  debit   openai/gpt-5...       -$0.0044 │
│ ...                                                       │
│ [Load more]  ← uses next_cursor                            │
└───────────────────────────────────────────────────┘
```

**New components:**

- `services/agent-console/src/components/WalletCard.tsx` — sourced from `getWallet`
- `services/agent-console/src/components/LedgerFeed.tsx` — sourced from `listLedger`,
  cursor-paginated, type-filter chip. Render `reference_id` as monospace; when prefix
  matches `agent:<uuid>:<n>` show a session-link affordance (link target is a future
  enhancement when SessionDetail spend lands)

**New page:** `services/agent-console/src/pages/Billing.tsx` — composes the two
components. Uses `useResource(() => getWallet(teamId), [teamId])` and a paginated
hook for ledger.

**Stories:** add `WalletCard.stories.tsx` + `LedgerFeed.stories.tsx` with a couple
of fixtures (loaded / empty / kill-switch-tripped / billing-misconfigured 503).

Also expose `getWallet` as a small badge on the existing AgentOverview StatStrip —
wallet is team-level, not agent-level, so it's a banner / small card above the
agent grid, not a per-agent tile. Skip if it complicates the overview; the Billing
tab is the primary surface.

### B10. Dock / nav wiring

Search the agent-console app shell for where "Agents" is registered (likely
`services/agent-console/app/layout.tsx` or a nav definitions file under
`src/components/dock-*`). Add a "Billing" entry pointing to `/billing`.

---

## Sequencing

1. **ai-gateway** A1 (middleware) → A2 (config) → A3 (ledger.Recent extension)
2. **ai-gateway** A4 (wallet handler) → A5 (ledger handler) → A6 (routes) → A7 (billing main) → A8 (smoke)
3. **ai-gateway** push to `feat/usage-and-wallet-endpoints`, verify local smoke
4. **posthog** B1 (settings) → B2 (client) → B3 (viewset) → B4 (urls) → B5 (perms)
5. **posthog** B7 (build:openapi), commit generated diff
6. **posthog** B8 (apiClient) → B9 (UI) → B10 (nav)
7. **posthog** B6 (janitor walletProxy delete) — last so the console has a working
   replacement before the old route disappears

Each numbered group is a logical commit on the respective branch.

---

## Wave 2 (out of scope here)

Captured so design choices in Wave 1 don't accidentally close these doors.

- **Per-turn spend in SessionDetail** — runner attaches `cost_usd` to each assistant
  turn when `/v1/usage/{id}` returns; janitor session detail surfaces it; no new
  endpoint needed
- **Per-agent ledger filter** — needs runner to stamp
  `agent:<app_id>:<session_id>:<turn>` so a single prefix filter works; backfill old
  rows or live with mixed format
- **Kill-switch wiring** — when billing's rolling-hour kill switch lands, populate
  the `KillSwitchLookup` impl; wallet response upgrades automatically
- **Holds / pricing detail** — `GET /v1/wallet/holds` (billing, lists in-flight
  holds with expiry) and `GET /v1/pricing/{model}` (billing, model rate sheet)
- **Provider health + ratelimit** — `/internal/health/providers` and
  `/internal/ratelimit/{team}` on `cmd/gateway` (state is gateway-pod-local), reusing
  the same `internalSecretRequired` middleware under an `/internal/*` prefix
- **Operator surface** — the reverted admin panel (kill-switch toggle, credits,
  pricing refresh, host overrides) is a separate concern with its own auth layer;
  it can sit next to billing's read surface but uses different bearers and an
  audit table

---

## Open implementation decisions to make as you go

- **Where to put the Wallet badge on the agent grid (B9 paragraph 2)** — only if it
  fits naturally; the Billing tab is the primary home
- **`scope_object = "ai_gateway"` registry location** — search for an existing
  enum; copy the pattern from a recent similar viewset (e.g. agent_application)
- **Whether `Spendable` needs its own `SpendableLookup` interface or can reuse
  `BalanceLookup`** — they're both on `*ledger.Store`; a single combined
  `WalletReadDeps.Store *ledger.Store` is simpler if test substitution isn't needed.
  Default to interfaces only when a test actually needs to substitute (per
  ai-gateway AGENTS.md "no interfaces invented for testability")
