# Design — control flows / approval-gated tool use

**Status:** draft (v0.2). **Owner:** ben.

This is `_TODO.md` item #3. It extends `AgentSpec` so an author can mark
individual tool calls as "requires approval". When the model tries to
invoke one, the platform queues an approval request and returns a
synthetic "queued + here's the link" result to the model — **the session
doesn't park**. The model can keep talking to the user, call other
(non-gated) tools, share the approval link, etc. When the approver
decides, the platform runs the tool with the approved args (option A,
[discussion thread in the plan history]) and injects the real result
back into the session as a synthetic tool_result message; the model
sees a normal tool result and reasons about what to do next.

> **Design pivot from v0.1 draft.** The original plan parked the
> session in `waiting` until the approval landed (mirroring
> `meta-ask-for-input`). v0.2 instead treats the approval queue as a
> session **side artifact** the model is told about and can continue to
> work around. This keeps the chat alive, removes the
> `pending_approval` vs `ask_for_input` wake conflict, and lets a Slack
> agent post the approval link and answer follow-ups while the
> approver acts on their own time.

## 1. Problem

Today, every tool a model invokes runs immediately. There is no human
review step between "model decides to call `posthog/team-delete` with
`team_id=42`" and "team 42 is gone". The platform is already conservative
about what tools an agent can be granted (spec freeze, allowlist), but
that's a coarse-grained, **design-time** control. We need a fine-grained,
**run-time** control for tool calls where the author wants a human in
the loop.

Concrete examples:

- An ops agent that can _propose_ infrastructure changes but only
  applies them once an on-call engineer confirms.
- A customer-support agent that drafts a refund and posts the proposed
  amount + reason; a billing lead approves before the refund actually
  fires.
- A code-review agent that wants to push a commit — author approves the
  diff first.

What `@posthog/meta-ask-for-input` _doesn't_ do: it asks the user a
free-form question. The model gets back a string and decides what to do
with it. There's no contract that "the next tool call I make is the
thing the user just approved". An approval gate is structurally
different — it's a yes/no on a _specific proposed tool invocation_ with
_concrete args_, where the platform — not the model — guarantees the
tool only fires on approval and only with the approved args.

## 2. What "approval-gated tool call" precisely means

A tool call is approval-gated when:

1. The tool's `ToolRef` in `AgentSpec` declares `requires_approval: true`.
2. The runner's dispatcher intercepts the invocation **before** the tool
   handler runs. It writes a `tool_approval_request` row, then returns a
   synthetic tool_result to the model containing the queue notice + a
   link to the approval surface.
3. The session **stays in its normal state** — `running` if the turn
   continues, `completed` if the model wraps up cleanly. Approval requests
   are session side artifacts, not state-machine vertices. The model can
   - communicate the link to the user ("I've queued the refund — your
     team lead can approve at <link>"),
   - call other (non-gated) tools to keep working,
   - answer follow-up questions on `/send`.
4. The approval surface (UI / MCP) shows: agent identity, session
   context, tool id + description, the model's proposed args, the
   assistant message that emitted the call (text + thinking blocks, so
   the approver sees the model's reasoning). The approver can:
   - **Approve as-is** — tool dispatches platform-side with the model's
     exact args. The real result lands as a synthetic tool_result.
   - **Approve with edits** — approver modifies args (only when the
     spec opts in via `allow_edit: true`), tool dispatches with edited
     args. The diff between proposed and decided args is the audit
     signal.
   - **Reject with reason** — no tool dispatch. A synthetic message
     telling the model "the call was rejected, reason: …" lands in
     `pending_inputs`.
5. On approval, the platform runs the tool with the approved args
   (option A in the design thread). The real result, the decision
   metadata (who, when, edited?), and the dispatch outcome (success or
   downstream tool failure) all land on the `tool_approval_request` row.
   A synthetic tool_result message ("tool X with request_id Y was
   approved, here's the result") is injected into `pending_inputs`. The
   model wakes on the next turn drain and sees a normal tool result.

### The "model is told" contract

The model **is** told its call queued for approval — without this it
can't communicate the link to the user or work around the pause. The
synthetic result on intercept looks like:

```json
{
  "role": "tool",
  "tool_call_id": "tc_abc",
  "content": {
    "approval": {
      "request_id": "ar_xyz",
      "state": "queued",
      "approver_hint": "an authorized admin on this team",
      "approval_url": "https://posthog.com/agents/<slug>/approvals/ar_xyz"
    }
  }
}
```

Authors should write their `agent.md` accordingly — "if a tool returns
`approval.state: queued`, share the `approval_url` with the user and
let them know it's pending review."

## 3. Spec config

New optional field on `ToolRefSchema` (defined in
`services/agent-shared/src/spec/spec.ts`):

```jsonc
{
  "tools": [
    {
      "id": "@posthog/team-delete",
      // NEW — when true, every invocation parks for approval.
      // Default: false.
      "requires_approval": true,

      // NEW — optional richer policy. When absent, defaults to
      // { approvers: ["team_admins"], allow_edit: false, ttl_ms: 86400000 }.
      "approval_policy": {
        // Who is allowed to approve. See §6.
        //   "team_admins"   — anyone with admin scope on the agent's team
        //                     (the only v0 option — see §6 for why)
        // Other scopes (`session_owner`, `agent_owner`, `team_members`,
        // `org_admins`) reserved for future plan revisions once the
        // principal-resolution story is sound for all trigger types.
        "approvers": ["team_admins"],

        // Can the approver edit args before approval? Default FALSE —
        // edits change who the audit log holds responsible. Authors
        // opt in only when they actually want approvers tweaking
        // values (refund-amount-tweak case).
        "allow_edit": false,

        // How long a tool_approval_request can sit before auto-rejecting
        // and surfacing an "approval_expired" message to the model.
        // Default: 24h.
        "ttl_ms": 86400000,

        // Allow non-human MCP callers (PAT-authed agent sessions) to
        // approve via the MCP path. Default FALSE — otherwise agent A
        // could approve agent B's gated calls just by sharing a team.
        // Authoring AI dry-run sandboxes flip this for self-testing.
        "allow_agent_approver": false,
      },
    },
    {
      "id": "@posthog/insight-query",
      // No requires_approval => runs immediately. Today's behavior.
    },
  ],
}
```

Backwards compatible: an agent with no `requires_approval` anywhere
behaves exactly as today.

**Why per-tool, not per-args-pattern (v0):** Per-tool keeps the spec
schema small and the runner intercept dead-simple (one boolean check).
Per-args-pattern (e.g. "approve `insight-create` but only if `query`
matches X") is a real future need but stacks onto this design without
breaking it — see §9 open question #2.

**Why on `ToolRef`, not a parallel `approvals` block:** matches the
existing shape of `tools[]` and keeps the approval policy adjacent to
the tool wiring. The downside is MCP-provided tools (`spec.mcps[]`) get
their tool list at runtime, so per-tool approval gating for MCP tools
needs a different shape — likely a top-level `mcp_approvals` policy
keyed by `mcp_id + tool_name_glob`. Punted to v1; see §9 #3.

Spec validation runs at freeze time (per `agent-authoring-flow.md` §3).
Invalid: `requires_approval: true` on a tool the agent doesn't actually
list; `ttl_ms` below 1 minute or above 7 days; `approvers: []`.

## 4. Dispatch flow + wake mechanics

### 4.1 The dispatcher intercept

`dispatchTool` in `services/agent-runner/src/loop/tool-dispatch.ts`
checks the resolved tool's `requires_approval` flag **before** invoking
the handler. If set:

1. Compute a canonical hash of the args (sort keys, JSON.stringify,
   sha256). See §5 for the canonicalisation rule.
2. UPSERT a `tool_approval_request` row keyed by `(session_id,
tool_name, args_hash)`. If a row with `state: pending` exists, return
   that row's id; never duplicate (idempotency). If a row exists in
   `rejected` / `expired` / `dispatched`, **insert a new row** —
   rejection is terminal for the original request, but the model can
   re-issue and ask for review again (with prior-rejection context
   surfaced in the synthetic result, see §4.4).
3. Return the **synthetic queued tool_result** to the runner (shape
   in §2). Dispatch never touches the actual tool handler.

The runner emits a `tool_result` lifecycle event as it would for any
dispatch, then moves on. No state-machine change — the session keeps
running. If this was the last tool call in the turn, the model gets the
synthetic result on the next turn and reacts (typically: tells the
user, asks if anything else is needed). If there are other (non-gated)
tools in the same turn, they dispatch normally.

### 4.2 State machine impact — none

The session stays in its current state. No `waiting` parking, no
`waiting_reason` field, no compose-with-`ask_for_input` conflict. A
session can have N open approval requests and still be `completed`,
`running`, or anything else — the approval rows are independent.

This is the key shift from v0.1. The model treats a queued approval
the same way it would treat a long-running tool that returns a "ticket
to check later" — completely natural in conversation.

### 4.3 The approval decision

Approver decides via UI / MCP. The approval endpoint:

1. Validates the calling principal against `approver_scope` on the row
   (§6).
2. Updates the row to `state: approving`, stamps `decision_by`,
   `decision_at`, `decision_reason`, optionally `decided_args`.
3. **Runs the tool platform-side** with the approved args. The
   dispatch uses the same `dispatchTool` path as normal — same sandbox,
   same secret broker, same integration credentials — but with
   `requires_approval` skipped for THIS dispatch (a one-shot bypass
   token tied to the approval id). The tool's real result + any
   downstream error lands in `dispatch_outcome JSONB` on the row.
4. Flips the row to `state: dispatched` (success) or `state:
dispatched_failed` (tool threw). The approval decision and the
   dispatch outcome are separately recorded — the human approved the
   intent; whether it executed cleanly is the tool's behaviour.
5. Writes a synthetic wake message into the session's `pending_inputs`.
   The QUEUED synthetic result (at intercept time, see §2) is a
   `tool_result` because it immediately follows the assistant's
   `tool_call` — Anthropic-compatible pairing.
   **The WAKE message (approve / reject / expire) is a `user` message,
   not a tool_result.** By the time the approval lands, the model has
   already produced an intervening assistant text reacting to the
   queued result; Anthropic (and other strict providers) reject a
   tool_result that doesn't immediately follow its matching tool_use in
   the prior assistant message. A user message carrying the same JSON
   envelope sidesteps the protocol violation — the model reads it as
   ordinary follow-up context.

```jsonc
// approve → dispatched
{
  "role": "user",
  "content": [{
    "type": "text",
    "text": "{\"approval\":{\"request_id\":\"ar_xyz\",\"state\":\"approved\",\"decided_by\":\"user_42\",\"edited_args\":false},\"result\":<actual tool result>}",
  }],
}

// approve → dispatched_failed
{
  "role": "user",
  "content": [{
    "type": "text",
    "text": "{\"approval\":{\"request_id\":\"ar_xyz\",\"state\":\"approved\",...},\"error\":\"<tool's error message>\"}",
  }],
}

// reject
{
  "role": "user",
  "content": [{
    "type": "text",
    "text": "{\"approval\":{\"request_id\":\"ar_xyz\",\"state\":\"rejected\",\"decided_by\":\"user_42\",\"reason\":\"<approver text>\"}}",
  }],
}

// expired (janitor sweep)
{
  "role": "user",
  "content": [{
    "type": "text",
    "text": "{\"approval\":{\"request_id\":\"ar_xyz\",\"state\":\"expired\"}}",
  }],
}
```

6. Wakes the session if it isn't running. Same enqueue path the
   `/send` endpoint already uses: write to `pending_inputs`, set
   `state: queued`, runner picks up next.

The model wakes, the next turn drains `pending_inputs` into
`conversation`, the model sees a normal tool_result message, and
continues the chat — typically with "the refund has been processed"
or "the approver said no because …".

### 4.4 Re-issue after rejection

If the model issues the same tool call after a prior request was
`rejected` / `expired`, the dispatcher creates a new row (rejection is
terminal for the original) but surfaces the prior decision in the new
synthetic queued result:

```jsonc
{
  "approval": {
    "request_id": "ar_new",
    "state": "queued",
    "approval_url": "...",
    "prior_decision": {
      "state": "rejected",
      "reason": "amount too high — try under $25",
    },
  },
}
```

This lets the model give the user context — "I tried this before and
the approver pushed back on the amount; I'm asking again with $25."
Without this, the model would re-propose the same args ad infinitum.

## 5. `tool_approval_request` storage

Dedicated table, FK to `agent_session`. Separate from the session JSONB
so the UI can render approvals per-team (cross-session listings, "what
needs my review?" dashboards) without walking session blobs.

```sql
CREATE TABLE agent_tool_approval_request (
    id              UUID PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES agent_session(id) ON DELETE CASCADE,
    application_id  UUID NOT NULL,  -- denormalised from session for app-level rollups
    team_id         BIGINT NOT NULL,  -- denormalised for fast tenant-scoped listing
    revision_id     UUID NOT NULL,    -- pin to the revision that proposed the call
    turn            INT NOT NULL,     -- which turn of the session emitted this
    tool_call_id    TEXT NOT NULL,    -- pi-ai ToolCall.id, surfaces in the synthetic result
    tool_name       TEXT NOT NULL,
    proposed_args   JSONB NOT NULL,
    args_hash       BYTEA NOT NULL,   -- sha256 of canonical_args (sort_keys + JSON.stringify)
    -- Snapshot of the assistant message that emitted the call.
    -- Lets the UI show the model's reasoning (text + thinking blocks)
    -- alongside the proposed args. Stored verbatim; we don't re-fetch
    -- the conversation later because compaction may truncate it.
    assistant_message JSONB NOT NULL,
    -- Approver scope resolved at request time. v0 = ["team_admins"];
    -- future revisions add session_owner / agent_owner / etc once the
    -- principal story is sound for non-UI triggers (see §6).
    approver_scope  JSONB NOT NULL,
    state           TEXT NOT NULL CHECK (state IN (
        'queued',              -- waiting for an approver
        'approving',           -- decision landed, tool dispatch in flight
        'dispatched',          -- tool ran successfully after approval
        'dispatched_failed',   -- tool ran but threw (audit: human approved intent, tool broke)
        'rejected',            -- approver said no
        'expired'              -- ttl elapsed before any decision
    )),
    decision_by     UUID NULL,
    decision_at     TIMESTAMPTZ NULL,
    decision_reason TEXT NULL,
    decided_args    JSONB NULL,        -- present when approver edited (allow_edit: true)
    dispatch_outcome JSONB NULL,       -- {result?: <real tool result>, error?: <message>}
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at      TIMESTAMPTZ NOT NULL,
    -- Idempotency: a queued request for the same canonical args is
    -- returned to the caller as-is, never duplicated. Hits the dispatcher
    -- intercept path when the model issues the same call twice while one
    -- is still pending. Filtered to state='queued' so subsequent issues
    -- after rejection / expiry create a new row.
    UNIQUE (session_id, tool_name, args_hash) WHERE state = 'queued'
);
CREATE INDEX ON agent_tool_approval_request (state, expires_at);
CREATE INDEX ON agent_tool_approval_request (team_id, state, created_at DESC);
CREATE INDEX ON agent_tool_approval_request (application_id, state, created_at DESC);
CREATE INDEX ON agent_tool_approval_request (session_id, created_at DESC);
```

Lives in the agent runtime DB alongside `agent_session`. `team_id` +
`application_id` are denormalised for fast tenant- and agent-scoped
listings per the [CLAUDE.md tenant-isolation rule](../../../CLAUDE.md).

### 5.1 Canonical args hashing

Keying on raw `proposed_args` JSONB would treat `{a:1, b:2}` and
`{b:2, a:1}` as distinct. To produce a stable hash:

1. **Recursive sort** all object keys (`Object.keys(...).sort()`).
2. **JSON.stringify** the result with no whitespace.
3. **SHA-256** the UTF-8 bytes.

Numbers, booleans, strings, arrays, null all pass through unchanged.
Floating-point edge cases (e.g. `1.0` vs `1`) are left as-is — the
model rarely produces them and a model that does will see new
approvals; that's fine.

Hash is computed once on intercept and stored on the row. The
idempotency check is a single index lookup.

## 6. Authorization — who can approve

### 6.1 v0: admin-only

The only `approvers` value v0 accepts is `["team_admins"]` (default).
The approval API requires the calling principal to be:

1. **A real human user**, authenticated via PostHog session cookie or
   a personal API key. PATs scoped to an agent ("agent service token")
   are rejected unless the spec sets `allow_agent_approver: true`.
2. **An admin of the agent's team**, per the existing PostHog ACL —
   any user with admin-level scope on the team that owns the agent
   application.

The rationale for starting here: the original plan defaulted to
`session_owner` + `team_members`. Both broke down on contact with
real-world triggers:

- **`session_owner`** only resolves to a real human for chat-trigger
  sessions with PAT auth. For Slack, the principal is a Slack-mapped
  user that often has no PostHog account (external customer in a
  shared channel); for webhook, the principal is whoever owns the
  webhook secret (the agent author, not the caller). Building the
  approval API on a notion that doesn't resolve gives us a feature
  that works in demos and fails in production.
- **`team_members`** lets anyone on the team approve, which means any
  team-scoped service PAT could too — including the PAT of a sibling
  agent. The whole point of approval gating is human oversight; that
  loophole defeats it.

Admin-only sidesteps both: admin scope is a real PostHog ACL row,
admins are humans (by org policy), and the surface for adding new
approver scopes can come later when we sort out the principal-
resolution story for each trigger type.

### 6.2 What's deferred (and why)

The richer set of approver scopes from the v0.1 draft —
`session_owner`, `agent_owner`, `team_members`, `org_admins` — are
**reserved for a future plan revision**. Each one has a real use case
but each also needs prerequisite work:

- **`session_owner`** — needs the `per-session access elevation`
  ([\_TODO #5](_TODO.md)) plan to land first so we have a consistent
  notion of "the human who initiated this session" across all
  triggers.
- **`agent_owner`** — works today (`AgentApplication.created_by`) but
  many production agents will be created by a service identity (the
  authoring AI), making `agent_owner` resolve to a non-human. Useful
  once we distinguish "human author" from "automation author."
- **`team_members`** — usable today but flips the "humans only"
  default. Probably gated on a `require_human_approver: false` spec
  field once we have a real use case.
- **`org_admins`** — useful for cross-team escalation. Pairs naturally
  with the future notification-escalation work (§7.3).

### 6.3 Audit

Every approval / rejection / expiry writes to the platform's existing
activity log (`activity-logging-expert` agent's territory) with
`action: approve_tool_call` / `reject_tool_call` / `expire_tool_call`,
`target: session_id`, `detail: { request_id, tool_name,
proposed_args, decided_args?, edited: boolean, reason?,
dispatch_outcome }`. The diff between `proposed_args` and `decided_args`
is the most important audit signal — surface it prominently in the
session timeline.

## 7. Approval surfaces

### 7.1 Link is the notification (v0)

The synthetic queued tool_result the model receives contains an
`approval_url` — a deep link to the PostHog approval page. The author's
`agent.md` instructs the model to share this URL with the user / on
the Slack thread / wherever the trigger surface lives. The user
forwards the link to an admin, or the admin already has access.

This deliberately punts on:

- **Push notifications** (Slack DMs to admins, email digests, etc.) —
  needs proper fan-out + dedupe and isn't required for the v0 loop to
  function. See §7.3.
- **Per-trigger affordances** (Slack button blocks, MCP resource
  embeds) — useful but trigger-specific work that should land once
  the v0 surface is real. See §7.3.

The link surface trades off polish for simplicity — until someone
actually uses an approval-gated agent in production we don't know
which fan-out pattern matters. Shipping the link first lets us learn
where the friction is.

### 7.2 PostHog UI

New tab on the session detail page: **"Approval requests"**. Lists
every row for the session in any state, with the queued ones at the
top. Each row shows:

- Tool id + description (pulled from the tool registry).
- Proposed args (read-only JSON view by default; editable when the
  spec declares `allow_edit: true`).
- The assistant message that emitted the call (text + thinking blocks,
  not just the tool args) so the approver sees the model's reasoning.
- For a queued row: `Approve` / `Reject` buttons + reason textbox.
- For a decided row: who decided, when, what they edited (if
  anything), and the dispatch outcome (success / tool error).

A separate team-level **"Approvals inbox"** scene (URL: `/agents/approvals`)
lists every queued request across every agent on the team — admin's
unified view. Filters by agent, tool, age. Same row UI; links to the
session detail tab.

Both views call `POST /agent_applications/:slug/approvals/:approvalId`
with `{ decision, edited_args?, reason? }`. The endpoint runs the
auth check (§6), updates the row, runs the dispatch + wake path (§4.3),
returns 200.

### 7.3 Deferred — to its own follow-up plan

These all matter; none of them are required for v0 to be useful.
Tracked as a follow-up: `approval-notifications.md` (TODO).

- **Notification fan-out + dedupe.** Push to admins via the existing
  PostHog notification system with single-claim semantics so a 50-
  person team doesn't pelt every admin per call.
- **Slack button blocks.** The Slack trigger renders the approval URL
  as an interactive button; clicking deep-links to the PostHog
  approval page.
- **Escalation policy.** No decision in 1h → notify the agent owner.
  No decision in 4h → notify org admins. 24h → expire.
- **TTL re-warning at `expires_at - 1h`** so a stale-but-still-valid
  request gets one more shot before expiring.

### 7.4 MCP path

New MCP tools on the `agent_stack` surface:

- `agent-applications-approvals-list({ application_id?, state?, limit? })` —
  returns approvals visible to the calling principal. Defaults to
  `state: queued`. Pagination via the standard limit/offset shape.
- `agent-applications-approvals-decide({ application_id, approval_id,
decision, edited_args?, reason? })` — same endpoint as the UI, same
  auth check.

The auth check enforces:

1. **Human principal only.** PATs scoped to an agent service are
   rejected unless the spec opts in via `allow_agent_approver: true`.
2. **Admin of the agent's team** (per §6).
3. **No self-approval.** A call where `request.user` is the agent's
   own service principal is rejected outright regardless of
   `allow_agent_approver` — agents can never approve their own gated
   calls, only those of a different agent within their team (and only
   when the spec opts in).

## 8. Composition with `meta-ask-for-input` and parallel tool calls

The v0.2 design eliminates the old composition headaches by NOT
parking the session:

- **`ask_for_input` still parks the session in `waiting`** (its
  existing behaviour). A gated tool call **doesn't** — the session
  stays `running` / `completed` / whatever it was. No state
  collision, no `waiting_reason` discriminator.
- **`/send` works the same as today** during an open approval request:
  it appends a user message and the model picks up on the next turn.
  The pending approval request is independent of the chat flow.
- **Multiple tool calls in one assistant message** are handled
  individually. The dispatcher loops over the model's tool calls; any
  gated ones return the synthetic queued result, any non-gated ones
  dispatch normally. The model sees a normal turn from its
  perspective: some calls returned data, some calls returned
  `{approval: {state: queued}}`. It reasons about the mix.
- **Belt-and-braces gating.** An author who wants the user to
  informally agree AND the platform to formally gate just composes
  `meta-ask-for-input` then a `requires_approval: true` tool. Both
  fire — the model asks "shall I?", the user says yes, the model
  calls the tool, the platform parks the call for admin review. The
  spec author decides which gates apply for which tool.

## 9. Open questions

1. **Per-args-pattern policy.** v0 is per-tool: any invocation of
   `team-delete` parks. Real use cases are finer-grained — "approve
   `insight-create` for read-only insights, gate destructive variants".
   Probable v1: extend `approval_policy` with `match: { args_jsonpath: ... }`
   evaluated at intercept time. Defer until we have ≥2 agents asking
   for it.
2. **Auto-approval rules.** Mirror image: "approve any `insight-create`
   where `team_id == owner_team`". Same `match:` schema as #1, with
   `action: "auto_approve"` instead of `"require_approval"`. Useful
   for reducing approver fatigue once we move beyond admin-only. Defer.
3. **MCP-tool approval gating.** Per §3, `spec.mcps[]` tools aren't
   listed individually in spec. Need a `mcp_approvals` policy keyed by
   `(mcp_id, tool_name_glob)`. Probably a v1 follow-up; v0 only gates
   tools that appear in `tools[]`.
4. **Edit beyond schema.** What if the approver edits args into a
   shape the tool's input schema rejects? Server-side: re-validate
   `decided_args` against the tool's Zod schema; reject the approval
   submission with a 422. UI: surface schema errors inline before
   submit.
5. **Cancel-after-approve.** The window between
   `state: approving` and `state: dispatched` is small but real —
   approver hits approve, regrets it, wants to cancel. v0 disallows
   (the dispatch is in flight). v1 could add a `cancelling` state
   that aborts mid-dispatch via the runner's existing AbortSignal.
6. **Rate limits.** A runaway agent could create thousands of pending
   approvals before anyone notices. Pair with
   [rate-limiting-sessions.md](rate-limiting-sessions.md): per-team
   daily cap on `tool_approval_request` rows. Defer to that plan.
7. **Side-effect compaction.** Long-running sessions ([long-running-
   sessions.md](long-running-sessions.md)) may compact the
   conversation. The approval row's `assistant_message` snapshot keeps
   the audit story whole even if the original conversation gets
   truncated. No skip-compaction rule needed (cf. v0.1, which needed
   one).

## 10. Rollout

Additive — disabled by default per tool. Existing agents see zero
behaviour change.

**v0 — foundation.** **Shipped.**

- ✅ `ToolRef.requires_approval` + `approval_policy` on
  [services/agent-shared/src/spec/spec.ts](../../../services/agent-shared/src/spec/spec.ts).
  Defaults match plan: `false`, `{approvers: ["team_admins"],
allow_edit: false, ttl_ms: 86400000, allow_agent_approver: false}`.
- ✅ `agent_tool_approval_request` table in
  [services/agent-migrations/migrations/](../../../services/agent-migrations/migrations/)
  (the migrations service that replaced the boot-time `SCHEMA_SQL` /
  rust sqlx setup as a side effect of this change).
- ✅ `ApprovalStore` interface + `MemoryApprovalStore` +
  `PgApprovalStore` in
  [services/agent-shared/src/persistence/](../../../services/agent-shared/src/persistence/).
- ✅ Dispatcher intercept in
  [services/agent-runner/src/loop/dispatch-one.ts](../../../services/agent-runner/src/loop/dispatch-one.ts):
  UPSERT-by-hash, synthetic queued tool_result, `prior_decision`
  surfaced on re-issue after terminal state.
- ✅ Janitor `/approvals/*` HTTP surface in
  [services/agent-janitor/src/server.ts](../../../services/agent-janitor/src/server.ts):
  `GET /approvals`, `GET /approvals/:id`, `POST /approvals/:id/decide`.
- ✅ Wake path. Decide-approve writes a sentinel
  `__POSTHOG_APPROVAL_DECIDED__:<id>` marker into `pending_inputs` and
  flips state to `queued`; the runner's turn-start
  ([approval-marker.ts](../../../services/agent-runner/src/loop/approval-marker.ts))
  recognises the marker, dispatches the tool via the existing
  `dispatchTool` path (full sandbox / secret / integration access),
  finalises the row with `markDispatched`, pushes a synthetic
  approved-or-failed tool_result. Decide-reject materialises the
  synthetic rejected tool_result inline.
- ✅ Janitor sweep: `expireQueued` past `expires_at`, injects the
  synthetic expired result into `pending_inputs`, wakes the session.
- ✅ Django proxy:
  [`agent-applications-approvals-list`](../../../products/agent_stack/backend/api.py),
  `agent-applications-approvals-retrieve`,
  `agent-applications-approvals-decide`. Team-admin only per §6.1.
  AGENT_DB never queried directly — proxied through
  `janitor_client.list_approvals` / `decide_approval`.
- ✅ e2e:
  [services/agent-tests/src/cases/approval-gated.test.ts](../../../services/agent-tests/src/cases/approval-gated.test.ts)
  covers happy-path / reject / idempotency / re-issue + prior_decision
  / expiry / mixed turn / custom-sandboxed-tool.
- ⏳ Activity-log integration (`approve_tool_call` /
  `reject_tool_call` / `expire_tool_call`) — deferred to v1.

**v1 — first real users + UI.** After v0.

- Pick one internal agent — the ops / infra-mutating one — and gate
  one destructive tool.
- Build the session-detail "Approval requests" tab + the team-level
  `/agents/approvals` inbox.
- Watch: false-positive rate (approver always says yes →
  `requires_approval` is wrong), expiry rate (approvers asleep at
  the wheel), edit rate (signals the model proposes bad args).
- Spin up the `approval-notifications.md` follow-up plan.

**v2 — broader scopes + MCP polish.** After v1.

- Surface `requires_approval` in the authoring wizard / MCP YAML.
- Document approval-gating in the authoring skill (heuristic: gate
  tools whose name contains `delete`, `remove`, `cancel`, `send` by
  default unless the author opts out).
- Land per-args-pattern policy if ≥2 agents are asking (open q #1).
- Open approver scopes beyond `team_admins` once principal-
  resolution is sound for each trigger type (see §6.2).

## 11. Dependencies + what this enables

**Hard depends on:** nothing — v0.2 doesn't park the session, so
`long-running-sessions.md` is no longer a prerequisite. (The session
keeps running; approvals are side artifacts.)

**Composes with:**

- [`per-session-access-elevation.md`](per-session-access-elevation.md) —
  needed before approver scopes can expand beyond `team_admins`
  (see §6.2).
- [`rate-limiting-sessions.md`](rate-limiting-sessions.md) — pair the
  per-session approval count with a per-team daily cap so a runaway
  agent can't flood the inbox.
- [`agent-authoring-flow.md`](agent-authoring-flow.md) — the authoring
  AI reasons about which tools to gate. Reference authoring skill
  should include heuristics ("tools whose name contains `delete`,
  `remove`, `cancel`, `send` warrant `requires_approval` by default
  unless the author explicitly opts out").

**What this unblocks:**

- A real "human-in-the-loop" story for agents that touch consequential
  state (refunds, deletes, deploys).
- `self-healing-agents` (future plan) — false-positive / expiry /
  edit-rate signals are first-class feedback for an agent that wants
  to refine its tool args before proposing them.
- Future `approval-notifications.md` plan (see §7.3) — push/email/Slack
  fan-out with dedupe + escalation; rides on top of v0's link surface.
