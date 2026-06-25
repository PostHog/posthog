# Identity & admission rebuild — authoritative provider + generic transport

**Branch:** `ben/agent-transport-identity` · **Status:** built + tested through the Slack ingress
**Spec rationale:** `~/.claude/plans/agent-platform-transport-identity-reframe.md`

## Status

**Done + green:**

- `Oauth2AuthProvider.exchange()` split (token+subject, no persist); `complete()` and admission share it. `fetchSubject` (userinfo) lifted to base — any oauth2 provider with `userinfo_url` can be authoritative.
- `transport.ts` (`TransportClaim`, `AdmissionResult`, `Transport`), `transport-binding-store.ts` (memory + pg), `admission.ts` (`AdmissionService.resolve`/`complete`).
- `spec.authoritative_provider` (zod + `spec_schema.py` mirror).
- `AgentTransportBinding` model + migration `0011` (applied to the test DB).
- Tests: `admission.test.ts` (7, PG-free, multi-provider/transport + per-request bearer + passthrough + fail-closed + replay), `transport-binding-store.test.ts` (4, real PG), `admission-e2e.test.ts` (2, real PG + real `dogs` IdP — full arc incl. one-identity-two-transports + the cred calling the protected API). agent-shared suite: 495 pass, no regressions.

**Ingress edge wiring — done + green:**

- `enqueue/admission-gate.ts` `buildAdmission()` builds an `AdmissionService` per revision (registry from `identity_providers` + decrypted env; null when no authoritative provider).
- Slack trigger (`triggers/slack.ts`): resolves admission before enqueue; `auth_required` → posts the link + returns `{ auth_required, provider, authorize_url }`, enqueues nothing; `admitted` → stamps `canonical_agent_user_id` on the principal; `passthrough`/`error` handled.
- Callback `/link/:provider/callback` branches to `AdmissionService.complete()` when `providerId === spec.authoritative_provider` (writes canonical + binding); other providers stay per-asker links.
- Secondary linking re-keyed: `agentUserIdForPrincipal` prefers `canonical_agent_user_id`.
- `transportBindings` wired through ingress `index.ts` + harness `cluster.ts`.
- `admission-cluster-e2e.test.ts` (2): Slack unbound → auth_required (no run) → link → admitted → agent runs; + passthrough runs immediately. agent-ingress: 141 pass; identity e2e suite: no regression.

## Follow-ups (post-review, tracked)

Code review pass done (see `CODE_REVIEW.md`, untracked). Addressed: authoritative-provider
validation (superRefine + tests) and the P0 edge-case unit tests (dangling binding, re-auth
account switch, complete() provider mismatch). Remaining, in priority order:

**Security / correctness**

- **T2 link delivery:** Slack posts the auth link in-thread (`TODO(admission)` in slack.ts) — make it ephemeral/DM so a channel member can't complete another user's link.
- **T1 per-sender on resume:** admission stamps the canonical id on the session-owner principal; on a shared/participant thread, secondary credentials should resolve per _message sender_, not the owner. Pre-existing ACL concern; thread the sender through.
- **Chat/HTTP admission:** `authoritative_provider` is enforced only on the Slack path today. Wire it into chat/MCP (the `verifyBearer` seam exists + is unit-tested but isn't connected to a transport). Decide whether a per-request posthog bearer satisfies the authoritative provider.

**Testing gaps (maximize integration/e2e)**

- **P1 (real-PG / runner integration):** secondary provider link resolves under the _canonical_ identity _through the runner_ (proves the `agentUserIdForPrincipal` re-key end-to-end, not just at unit level).
- **P1 (real-PG):** re-auth-replaces-binding orphaning the prior canonical's secondary creds — the account-switch/takeover boundary, currently only unit-tested.
- **P2 (cluster e2e):** assert the auth link is delivered via `postEphemeral` (once T2 is fixed) — the harness already intercepts `slack.com/api/`, so assert the method/recipient.
- **P2 (cluster e2e):** concurrent first-contact race (two messages before any binding) → at most one canonical identity, no duplicate-key error.
- **Python:** `spec_schema.py` can't express the cross-field authoritative_provider rule in pure JSON Schema (the janitor's zod gate enforces it). If a Django-side guard is wanted, add it in the promote/validate path.

## What changes, in one paragraph

The entrypoint (Slack/Discord/HTTP) stops being the identity authority. Each transport only
proves authenticity and emits a **`TransportClaim`** (who the sender is, per that transport). An
agent declares **one authoritative identity provider**. Before a session runs, the **ingress edge**
must resolve a **verified canonical identity** from that provider for the claim — either from a
durable prior binding, or from a per-request credential (HTTP bearer), or by returning an
**auth block** (a link to authenticate) and _not_ enqueuing. The canonical identity is the source
of truth; every other provider (PostHog, GitHub, …) links _to it_.

## Model

```text
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
  Discord binds to the _same_ canonical row (same subject).
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

| File                                       | What                                                                                                          |
| ------------------------------------------ | ------------------------------------------------------------------------------------------------------------- |
| `runtime/transport.ts` (new)               | `TransportClaim`, `AdmissionResult`, `Transport` (claim extraction + auth-block delivery)                     |
| `runtime/transport-binding-store.ts` (new) | `TransportBinding`, `TransportBindingStore` (iface), `MemoryTransportBindingStore`, `PgTransportBindingStore` |
| `runtime/admission.ts` (new)               | `AdmissionService.resolve()` / `.complete()` — the edge engine                                                |
| `runtime/oauth2-identity-provider.ts`      | extract `exchange()`; `complete()` becomes a thin wrapper                                                     |
| `runtime/identity-provider.ts`             | add `exchange()` to the interface; add optional `verifyBearer()` (per-request proof, HTTP)                    |
| `spec/spec.ts`                             | `spec.authoritative_provider?: string` (refs an `identity_providers[]` id; must establish identity)           |

## Authorization

No bespoke policy. "Who may use this agent" falls out of _which_ authoritative provider is configured
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
