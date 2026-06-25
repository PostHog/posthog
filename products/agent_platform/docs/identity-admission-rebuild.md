# Identity & admission rebuild — authoritative provider + generic transport

**Branch:** `ben/agent-transport-identity` · **Status:** core built + tested; ingress wiring next
**Spec rationale:** `~/.claude/plans/agent-platform-transport-identity-reframe.md`

## Status

**Done + green:**
- `Oauth2AuthProvider.exchange()` split (token+subject, no persist); `complete()` and admission share it. `fetchSubject` (userinfo) lifted to base — any oauth2 provider with `userinfo_url` can be authoritative.
- `transport.ts` (`TransportClaim`, `AdmissionResult`, `Transport`), `transport-binding-store.ts` (memory + pg), `admission.ts` (`AdmissionService.resolve`/`complete`).
- `spec.authoritative_provider` (zod + `spec_schema.py` mirror).
- `AgentTransportBinding` model + migration `0010` (applied to the test DB).
- Tests: `admission.test.ts` (7, PG-free, multi-provider/transport + per-request bearer + passthrough + fail-closed + replay), `transport-binding-store.test.ts` (4, real PG), `admission-e2e.test.ts` (2, real PG + real `dogs` IdP — full arc incl. one-identity-two-transports + the cred calling the protected API). agent-shared suite: 495 pass, no regressions.

**Next (clearly scoped):**
- Wire admission into the ingress edge: Slack trigger delivers the auth block as a DM/ephemeral and skips enqueue on `auth_required`; HTTP/chat returns `401 + { auth_required }`. Route `/link/:provider/callback` branches to `AdmissionService.complete()` when the link-state is an admission link.
- Re-key secondary provider linking (`identity-gate.ts` `agentUserIdForPrincipal`) to the canonical identity so a person's GitHub/Grafana links are shared across transports.
- Cluster e2e through the real Express ingress + faux inference.

## What changes, in one paragraph

The entrypoint (Slack/Discord/HTTP) stops being the identity authority. Each transport only
proves authenticity and emits a **`TransportClaim`** (who the sender is, per that transport). An
agent declares **one authoritative identity provider**. Before a session runs, the **ingress edge**
must resolve a **verified canonical identity** from that provider for the claim — either from a
durable prior binding, or from a per-request credential (HTTP bearer), or by returning an
**auth block** (a link to authenticate) and *not* enqueuing. The canonical identity is the source
of truth; every other provider (PostHog, GitHub, …) links *to it*.

## Model

```
TransportClaim                AdmissionService                 Canonical identity
{ transport: 'slack',   ──▶   resolve(claim, app, rev)   ──▶   AgentUser{ kind=<authoritative
  subject: 'T01:U01',          │                                provider>, id=<subject> }
  bearer?, attrs? }            ├─ no authoritative provider → { passthrough }   (today's behaviour)
                               ├─ binding exists            → { admitted, identity }
                               ├─ per-request bearer verifies→ { admitted, identity } (HTTP)
                               └─ else initiate link        → { auth_required, authorizeUrl }
```

### Canonical identity (reuses `AgentUser`)

- A **transport principal** is an `AgentUser` keyed `(application, kind=transport, id=transportSubject)`
  — exactly what the Slack trigger already creates (`kind='slack'`, `id='T01:U01'`).
- A **canonical identity** is an `AgentUser` keyed `(application, kind=<authoritative provider id>,
  id=<subject>)` — created at link completion from the provider's proven `subject`.
- A **binding** (`agent_transport_binding`, new) maps transport-AgentUser → canonical-AgentUser.
  Durable + revocable (unlink = delete the binding). One canonical identity, many transport bindings
  → "auth once via Slack, every future Slack turn resolves the same identity"; the same person via
  Discord binds to the *same* canonical row (same subject).
- Secondary providers' `AgentIdentityCredential` rows hang off the **canonical** AgentUser id, so a
  person's GitHub/Grafana links are shared across all their transports.

### Why the canonical id isn't known at `initiate()`

The authoritative subject only exists after the OAuth round-trip. So:
- `initiate()` binds the link-state to the **transport** AgentUser (no schema change — link-state
  already carries `agentUserId`).
- `complete()` (admission variant) exchanges the code, derives the subject, **finds/creates the
  canonical AgentUser**, persists the authoritative credential under it, and **writes the binding**
  transport→canonical.

To reuse OAuth mechanics without duplicating them, `Oauth2AuthProvider` exposes
`exchange(stateId, query) → { state, stored, subject, scopes }` (token exchange + `deriveSubject`,
**no persist**). The existing per-asker `complete()` persists by `state.agentUserId`; admission
persists by the canonical id + writes the binding. One code path for the crypto, two persistence
policies.

## New / changed code (agent-shared)

| File | What |
| --- | --- |
| `runtime/transport.ts` (new) | `TransportClaim`, `AdmissionResult`, `Transport` (claim extraction + auth-block delivery) |
| `runtime/transport-binding-store.ts` (new) | `TransportBinding`, `TransportBindingStore` (iface), `MemoryTransportBindingStore`, `PgTransportBindingStore` |
| `runtime/admission.ts` (new) | `AdmissionService.resolve()` / `.complete()` — the edge engine |
| `runtime/oauth2-identity-provider.ts` | extract `exchange()`; `complete()` becomes a thin wrapper |
| `runtime/identity-provider.ts` | add `exchange()` to the interface; add optional `verifyBearer()` (per-request proof, HTTP) |
| `spec/spec.ts` | `spec.authoritative_provider?: string` (refs an `identity_providers[]` id; must establish identity) |

## Authorization

No bespoke policy. "Who may use this agent" falls out of *which* authoritative provider is configured
and how (domain-restricted Google app, org-scoped PostHog OAuth) plus the existing `auth.modes`
`audience` gate for the HTTP path. Out of scope for v1 beyond "can you authenticate with the
authoritative provider at all".

## Verified-principal invariant

With edge admission, a non-`public` agent only enqueues a session once a canonical identity resolves.
`session.principal` carries `{ transport claim } + { verified: { provider, subject, canonicalId } }`.
`anonymous` survives only for agents that opt into `public`.

## Test strategy

1. **agent-shared integration test** (fast, no Express/queue): real `Oauth2AuthProvider` + in-test
   OAuth server (fake `HttpFetcher`) + in-memory stores. Proves the full arc:
   claim → auth_required → OAuth round-trip → binding written + canonical created → re-admit →
   second transport binds to same canonical → second (secondary) provider links to same canonical →
   multi-provider agent. This is the architecture-level e2e.
2. **cluster e2e** (`agent-tests`, real PG/Redis/Kafka + `dogs` IdP + faux inference): Slack mention →
   edge admission auth block delivered to the user → OAuth callback writes binding → next mention is
   admitted → tool runs. Plus the same arc via the HTTP/JWT transport, proving transport-agnosticism.

## Open / deferred

- Per-request HTTP proof (`verifyBearer`) for the posthog authoritative provider — design the seam now,
  full wire later.
- Pg binding store + Django model/migration for `agent_transport_binding` (needed for cluster e2e).
- Unlink surface (slash command / console).
