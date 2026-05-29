# Design — per-session access elevation

**Status:** v0 shipped (security patch + storage + check). v1 (UI surfaces + activity log) pending. **Owner:** dylan.

This is `_TODO.md` item #5. By default a session is private to its
initiating principal. When a second user tries to interact, the platform
rejects AND posts a deterministic elevation surface — a button / link
where the original owner (or an authorized team member) can grant
access to either the specific other user or everyone in the workspace.

## 1. Problem

Today's enforcement is asymmetric:

- **Chat & webhook `/send`** call `principalsMatch(existing.principal,
principalToSession(auth.principal))` in
  `services/agent-ingress/src/triggers/chat.ts:103`. Mismatch → 403
  `principal_mismatch`. Good.
- **Slack thread replies** match by
  `externalKey = slack:${channel}:${thread_ts || ts}` and call
  `enqueueOrResume()` directly
  (`services/agent-ingress/src/triggers/slack.ts:83-99`). **No
  principal check.** Anyone who can post in the thread can advance the
  session. This is a real privacy gap — a teammate scrolling Slack
  can drop into someone else's agent thread and the agent will respond.

Even fixing the Slack gap to be symmetric with `/send` only gets us to
"strict, blanket rejection". The user experience is: a teammate types a
follow-up, sees nothing (or sees an opaque error toast in the chat UI),
and the thread silently dies. No path forward.

What we want:

1. **Reject** the second user's input — never advance the session
   with an unverified principal.
2. **Surface** a deterministic elevation prompt — a Slack thread reply
   ("@otheruser tried to interact with this thread; @owner can grant
   them access here: <link>") or, in the chat UI, an inline 403 panel
   with the same elevation link.
3. **Grant** — the original owner clicks through and chooses:
   "Allow @otheruser only" OR "Allow everyone in #channel" OR "Allow
   anyone in team T" OR "Decline".
4. **Resume** — once granted, the rejected message is replayed (or a
   "👋 catch-up, here's what changed" synthetic input drops in) and
   the session continues.
5. **Audit** — every grant / revoke / rejected attempt lands in the
   activity log with principal, scope, and timestamp.

## 2. What "session ACL" precisely means

A session has a **primary principal** (today's `session.principal`) and
a new **allowlist** of additional principals + scopes. A `/send` (any
trigger) advances the session only if the caller's resolved principal
matches the primary OR is covered by an allowlist entry.

An allowlist entry is one of:

- **Specific principal** — `{ kind, id, team_id }`. Exact match.
- **Scope grant** — `{ scope: 'team_members', team_id }` (any active
  member of team T), `{ scope: 'org_admins', org_id }`, or, for Slack
  specifically, `{ scope: 'slack_channel', channel_id }` (anyone who
  can post in the channel).

Every entry has metadata: `granted_by`, `granted_at`, optional
`expires_at`, optional `reason`, and a `state` (`active` | `revoked`).
Revoked entries are kept for audit, ignored for matching.

The **primary principal** is immutable and special: it's the only
principal that can grant elevation by default (see §6 for delegation).

## 3. Session row additions

New nullable fields on `AgentSession` in
`services/agent-shared/src/spec/spec.ts`:

```typescript
export interface SessionAclEntry {
  // exactly one of `principal` | `scope` is set
  principal?: SessionPrincipal
  scope?:
    | { kind: 'team_members'; team_id: number }
    | { kind: 'org_admins'; org_id: string }
    | { kind: 'slack_channel'; channel_id: string; workspace_id: string }

  granted_by: SessionPrincipal // who clicked the grant button
  granted_at: string // ISO timestamp
  expires_at: string | null // null = forever
  reason: string | null // free-form text from the grant UI
  state: 'active' | 'revoked'
  revoked_by?: SessionPrincipal
  revoked_at?: string
  revoked_reason?: string
}

export interface AgentSession {
  // ... existing fields ...
  acl: SessionAclEntry[] // NEW. default []. primary principal not included.
  pending_elevation_requests: PendingElevationRequest[] // NEW. see §5.
}

export interface PendingElevationRequest {
  id: string
  requester: SessionPrincipal // who tried and was rejected
  requester_display: string // "@bob (Slack)" / "bob@posthog.com"
  trigger: 'chat' | 'webhook' | 'slack'
  proposed_message: ConversationMessage // what they tried to send
  created_at: string
  state: 'pending' | 'granted' | 'declined' | 'expired'
  decision_at?: string
  decision_by?: SessionPrincipal
}
```

Choice: embed in the session JSONB row (not new tables). Justification:
both arrays grow slowly per session (typical sessions: 0 entries;
worst-case: a Slack thread that elevates a handful of users). The
session row is already the natural locality boundary — every advance
already reads/writes it.

A new table `agent_session_acl_audit` lives **alongside** the JSONB,
write-only, for cross-session auditing:

```sql
CREATE TABLE agent_session_acl_audit (
    id            UUID PRIMARY KEY,
    session_id    UUID NOT NULL REFERENCES agent_session(id) ON DELETE CASCADE,
    team_id       BIGINT NOT NULL,
    action        TEXT NOT NULL CHECK (action IN
                    ('grant', 'revoke', 'elevation_requested', 'elevation_declined', 'elevation_expired')),
    actor         JSONB NOT NULL,        -- SessionPrincipal
    target        JSONB NOT NULL,        -- SessionPrincipal or scope
    reason        TEXT,
    created_at    TIMESTAMP NOT NULL DEFAULT now()
);
CREATE INDEX ON agent_session_acl_audit (team_id, created_at DESC);
CREATE INDEX ON agent_session_acl_audit (session_id, created_at DESC);
```

`team_id` is denormalized for the tenant-isolation rule
(see [CLAUDE.md](../../../CLAUDE.md)). The same data is also written to
PostHog's main `activity_log` so it shows up in the team's "Recent
activity" stream. The dedicated table exists for performant per-session
queries (the activity log is a single denormalized table across the
product).

## 4. Symmetric enforcement — close the Slack gap first

Independently of the elevation flow, fix the existing gap:

- `services/agent-ingress/src/triggers/slack.ts` — when
  `enqueueOrResume()` finds an existing session, resolve the Slack
  reply's sender to a `SessionPrincipal` and run the same
  `principalsMatch(existing.principal, ...) || aclAllows(existing.acl, ...)`
  check the chat trigger does.
- On mismatch: do **not** advance the session. Create a
  `PendingElevationRequest`. Post the elevation surface back to the
  Slack thread (§5.2). Return 200 to Slack (we acknowledged the event)
  but with `result: elevation_required`.

This is a small refactor: extract `requireAclAccess(session, incoming)`
into `agent-ingress/src/auth/acl.ts`, call it from chat, webhook, and
slack triggers identically.

## 5. Elevation flow

### 5.1 Rejection — what happens to the rejected message

When `requireAclAccess` returns "denied", the trigger:

1. Creates a `PendingElevationRequest` on the session, including the
   would-be `ConversationMessage` (so a grant can replay it). Cap the
   list at 5 active pending requests per session; older ones get state
   `expired` and the user is asked to retry.
2. Persists a single audit row (action `elevation_requested`).
3. Returns / posts the elevation surface (§5.2 / §5.3).

The message is **never** put into `pending_inputs`. The runner never
sees it. On grant, the API replays it into `pending_inputs` and
re-queues the session, same path as today's `/send`.

### 5.2 Slack — the elevation message

The Slack trigger posts back to the thread using the existing
`slackPostMessageV1`-style call (the runner already uses
`chat.postMessage` with `thread_ts`; ingress can reuse the same
integration token). The posted message uses Slack blocks for the
buttons:

```text
🔒 @bob, this thread is owned by @alice. I can't reply to you yet.

[ Grant @bob access ]   [ Allow anyone in this channel ]   [ Decline ]

@alice can decide above, or use the agent's web UI:
https://posthog.com/agents/<app_slug>/sessions/<session_id>?elevation=<req_id>
```

Buttons send Slack interactivity events to a new endpoint
`/slack/elevation-decision`. The handler:

- Resolves the clicking Slack user → `SessionPrincipal`.
- Checks that the clicker is allowed to grant — by default, only the
  session's primary principal can grant; see §6 for delegation.
- Writes the ACL entry, replays the pending message, updates the Slack
  message in-place to "✓ @bob can now reply to this thread" (and lists
  the grant for transparency).

Failure modes:

- Wrong Slack user clicks → ephemeral reply "Only @alice can grant
  access" (not a thread message, to avoid noise).
- Slack token expired / integration removed → fall back to the deep-link;
  the in-thread surface still _shows_ the link.

### 5.3 Chat UI — the elevation panel

The chat UI is the React surface inside PostHog itself. When the
trigger returns 403 with `error: 'elevation_required'`, the response
body includes:

```jsonc
{
  "error": "elevation_required",
  "elevation_request_id": "...",
  "owner": { "kind": "...", "display": "Alice" },
  "agent_slug": "...",
  "session_id": "...",
  "elevation_url": "https://posthog.com/agents/<app_slug>/sessions/<session_id>?elevation=<req_id>",
}
```

The chat UI renders an inline panel: "You're not the owner of this
conversation. Alice can grant access here." with a copy-link button.
If the current user _is_ the owner, the same panel offers the grant
controls directly (no redirect needed).

### 5.4 Webhook — minimal surface

Webhooks don't have a UI surface to post to. The 403 response carries
the same `elevation_url`. Operators see this in their logs / observers
and grant out-of-band via the PostHog UI. No automated retry — webhook
callers can re-send once granted.

### 5.5 The grant UI (PostHog scene)

The `elevation_url` lands on a new scene under
`/agents/<app_slug>/sessions/<id>` with the `?elevation=<req_id>`
query param expanding the elevation panel. Owner sees:

- Who's asking (`requester_display`, trigger)
- What they tried to send (first 200 chars of `proposed_message`)
- Three buttons: **Allow this person**, **Allow scope** (with a
  scope-picker for `team_members` / `slack_channel` / etc.), **Decline**
- Optional reason textarea
- Optional expiry: "Forever" / "24h" / "Until this session ends"

Submit → `POST /agent-sessions/:id/acl/grant` with
`{ elevation_request_id, decision, scope?, reason?, expires_in_ms? }`.
The endpoint runs the authorization check, mutates `acl` +
`pending_elevation_requests` atomically, runs the replay, returns 200.

## 6. Who can grant — delegation rules

Default: only the **primary principal** can grant elevation. This is
the most defensible default (the initiator owns the session) and the
easiest to explain.

Delegation: an existing allowlist entry with the new `can_delegate: true`
flag lets the holder grant further elevation. Useful for ops scenarios
where the original owner went offline and a co-owner needs to bring a
new person in. Spec exposure:

- The grant UI has a checkbox "this user can grant further access" —
  off by default.
- A `team_members` scope grant implicitly does **not** delegate; team
  members can chat but not invite outsiders.
- Org admins can always grant on any session in their org (super-user
  override), to handle abandoned sessions. This is audited heavily.

The grant endpoint enforces:

```text
allowed_to_grant(actor, session) :=
    actor == session.primary_principal
    OR (actor in session.acl WHERE state='active' AND can_delegate=true)
    OR actor.kind == 'posthog_internal' AND actor.role == 'org_admin' AND actor.org_id == session.org_id
```

## 7. Composition with `AgentSpec.auth`

`spec.auth.mode` already gates _whether a principal can trigger this
agent at all_ (public / pat / posthog_internal / shared_secret). That
check happens **first** — a request that fails `spec.auth` never gets
to the session ACL check.

The session ACL operates one layer below: among principals that
`spec.auth` permits, only the initiator + ACL grants can advance a
specific session. Two layers:

1. **Agent-level** (`spec.auth`): "can this person _ever_ talk to this
   agent?"
2. **Session-level** (this design): "can this person talk to _this
   specific_ session?"

This composes cleanly with the approval-gated tools plan: that plan's
`approvers` list (`session_owner`, `team_members`, ...) is resolved
against the same `SessionPrincipal` shape. A user who's been ACL'd into
a session via `team_members` scope automatically becomes eligible to
approve if the approval policy says `approvers: ["team_members"]`.

## 8. Audit

Every grant, revoke, decline, and rejection writes:

- A row to `agent_session_acl_audit` (per §3).
- A row to PostHog's main `activity_log` so it shows up in the team's
  audit stream alongside other product changes.

Activity log shape (using the activity-logging-expert agent's
conventions):

```python
log_activity(
    organization_id=session.team.organization_id,
    team_id=session.team_id,
    user=actor_user,
    item_id=session.id,
    scope="AgentSession",
    activity="acl_granted",
    detail={
        "name": f"session-{session_short_id}",
        "changes": [{
            "type": "AgentSessionAcl",
            "action": "added",
            "field": "acl",
            "before": None,
            "after": {"target": ..., "scope": ..., "reason": ...},
        }]
    }
)
```

Surfacing: a "Session activity" tab on the session detail page shows
the full ACL history; a per-team filter on the main activity log
catches everything.

## 9. Open questions

1. **Replay vs synthetic catch-up.** When a grant lands, do we replay
   the rejected message verbatim into `pending_inputs`, or insert a
   synthetic system note ("@bob joined this thread. Their message:
   ...") so the model knows context shifted? Probably replay verbatim;
   the model already has the assistant message before it, so the new
   user turn reads naturally. The system note is a nice-to-have if it
   helps continuity.
2. **Multi-message backlog.** If @bob types five Slack messages before
   @alice grants, do we replay all five, or only the last? Cap at 5
   `PendingElevationRequest` rows (§5.1); on grant, replay all 5
   pending messages **in order** as a single batch into
   `pending_inputs`. Simpler than picking.
3. **Slack DMs vs channels.** A Slack thread elevation surface
   "Allow anyone in this channel" is meaningless in a DM. Detect DM
   channel kind and hide that option.
4. **Public agents (`spec.auth.mode = "public"`).** An agent that
   anyone can trigger probably shouldn't have session ACLs at all
   (the privacy boundary is by-session-id alone). Decision: respect
   the same primary-principal rule but make the elevation surface
   silent (no Slack ping; just return 403 + URL). The owner can elevate
   if they want; most won't. _Or_ skip session ACLs entirely for
   public agents — feels right since "public" is opting into wide
   access. Lean toward the latter; document the trade-off.
5. **Cross-team safety.** If @bob is in team T1 and the session was
   triggered in team T2, what happens? The agent itself lives in T2.
   `spec.auth` already gates this. If it permitted @bob, the elevation
   flow proceeds; @alice still has to grant. The grant API additionally
   re-checks the resolved principal at grant time (a user who lost
   team membership between request and grant can't be elevated).
6. **Revocation timing.** When a grant is revoked, does the session
   immediately move out of `waiting` if the revoked party was its
   `session.principal_id` for that turn? Probably no — the principal
   was valid at the time the turn started; revocation prevents
   _future_ advances. Document and stick with this.
7. **Composition with long-running `suspended`.** A 7-day session that
   accumulates ACL entries: at compaction the ACL is preserved
   verbatim. The `pending_elevation_requests` array is auto-pruned of
   `expired` entries on every sweep so the row doesn't bloat.
8. **MCP path for grants.** Should an authoring AI / reviewer agent be
   able to grant elevation programmatically? Probably yes, via an MCP
   tool `agent-platform-session-grant-acl`. Auth: caller's principal
   must satisfy `allowed_to_grant` (§6). v1.
9. **"Allow @user across all my agents."** A natural escalation:
   grant @bob access to any session @alice ever creates. Out of scope
   here — that's a user-preference, not a session ACL. Could live on
   a new `AgentDefaultAcl` table keyed by `(owner_user_id, target)`.
   Punt to a follow-up.
10. **Notification UX.** Pending elevation requests should ping the
    primary principal (Slack DM if they have an integration, email
    otherwise) — they may not see the in-thread message. Reuse the
    `sending-notifications` skill once it has a session-event path.

## 10. Rollout

This is additive — disabled by default per agent? No, it's a security
fix and should be enabled platform-wide. Phases:

**v0** (foundation — security fix) — **✅ shipped**:

- Extracted `requireAclAccess(session, incoming)` into
  `services/agent-ingress/src/enqueue/acl.ts` and applied uniformly in
  `chat /run` + `/send`, `webhook`, `slack`, and `mcp tools/call ask`
  (continuation + fresh-session). Closed the Slack thread-resume bypass.
- Tightened `principalsMatch` to require `id` equality for
  identity-bearing kinds (`slack`, etc.) — the prior "kind equality is
  the contract" fallthrough matched two different Slack users as the
  same principal.
- Added `acl` + `pending_elevation_requests` JSONB columns to
  `agent_session` (migration
  `services/agent-migrations/migrations/1780071167943_session_acl.sql`,
  default `[]`).
- Threaded the new fields through `AgentSession`, `MemorySessionQueue`,
  `PgSessionQueue`, and `enqueueOrResume`. `enqueueOrResume` now
  returns a discriminated `EnqueueOutcome` (`created` | `resumed` |
  `elevation_required`).
- On denial: a `PendingElevationRequest` is recorded on the session
  (capped at 5 active pending entries; older ones expire). The trigger
  responds with 403 + `{ error: 'elevation_required',
elevation_request_id, session_id, owner_display }` for HTTP triggers,
  or 200 + `elevation_required: true` for Slack (events callback expects
  200).
- e2e coverage: extended `slack-trigger.test.ts` ("different user in
  same thread → elevation_required") and `strict-principal.test.ts`
  ("/send with a different PAT → 403 elevation_required").

Deferred from v0 (rolled into v1):

- `agent_session_acl_audit` table + Django model. The PendingElevationRequest
  row on the session is sufficient v0 audit; the cross-session denormalized
  table lands with v1's UI.
- Activity-log integration. Lands with v1 alongside the rest of the
  cross-service activity-log helper.
- `elevation_url` in the response — no UI to point at yet; the
  v1 surface will populate it.

**v1** (UX):

- **Slack interactivity handler ✅ shipped:** ingress now exposes
  `POST /agents/<slug>/slack/interactivity`, parses the form-encoded
  `payload=<json>` body, verifies the signing secret, and dispatches
  via the shared `authorizeGrant` / `applyElevationGrant` /
  `applyElevationDecline` helpers in
  `services/agent-ingress/src/enqueue/acl.ts`. Owner-only authorisation
  (delegated grants are v2); non-owners get a Slack-style ephemeral
  response. Granting writes the ACL entry, replays the requester's
  proposed message into `pending_inputs`, flips state to `queued` so
  the runner picks it up on the next turn.
- **Pending — outbound Slack post (blocks message in the thread on
  rejection).** The Slack bot token already exists in PostHog: every
  team can connect Slack via Settings → Integrations and the token
  lands in `posthog/models/integration.py:147` alongside the same
  table HogFunctions reads from. The agent platform just hasn't been
  wired to that table yet — `resolveIntegrations` in
  `services/agent-runner/src/index.ts:140` is a `() => ({})` stub.
  Once a small Django proxy + a runner/ingress resolver lands (tracked
  as a separate task — see `_TODO.md`), every Slack-using agent works
  in prod, not just the elevation post. The elevation outbound becomes
  a one-call addition: `slackPostMessageV1` with the team's token, the
  thread_ts from the rejected event, and a blocks payload built from
  `encodeElevationActionValue` (already exported from
  `services/agent-ingress/src/triggers/slack.ts`).
- Build the chat UI inline elevation panel.
- Build the per-session ACL management scene in PostHog (grant /
  revoke / view audit). Will reuse the same `applyElevationGrant` /
  `applyElevationDecline` helpers the Slack interactivity handler now
  shares.
- Notifications to the primary principal (Slack DM / email).

**v2** (broad):

- Delegation flag in the grant UI.
- Org-admin super-user grant path (audited).
- MCP grant tool (open q #8).
- Document in the authoring skill — "your agent's sessions are
  private by default; here's how to expand access".

## 11. Dependencies + what this enables

**Depends on:**

- Symmetric principal enforcement across triggers (the Slack gap fix).
  Bundled into v0 of this plan.
- Activity log adoption in the agent platform. This plan introduces
  it; the [approval-gated tools plan](approval-gated-tools.md) and
  future plans piggyback on the same wiring.
- `long-running-sessions.md` — multi-day Slack threads are the
  motivating use case for elevation. Compaction must preserve ACL +
  prune stale `pending_elevation_requests`.

**Enables / interacts with:**

- [`approval-gated-tools.md`](approval-gated-tools.md) — the
  `approvers` policy resolves against the same principal model. ACL
  grants automatically widen the eligible approver set when
  `approvers: ["team_members"]` is configured.
- `_TODO` #4 (rate limiting) — pending elevation requests count
  against a session's "open ask" budget so a spammer can't flood the
  owner with grant prompts.
- `agent-authoring-flow.md` — the reference authoring skill should
  surface the ACL model so the authoring AI understands "sessions are
  private; an author doesn't pre-grant other users".
- A future "shared agents" plan (out of scope): if PostHog ever wants
  agents owned by an org-wide identity (e.g. `@incident-bot`),
  elevation is the natural building block — the org-wide identity is
  the primary principal, members are pre-allowlisted via a
  `team_members` scope grant baked into the agent's spec.
