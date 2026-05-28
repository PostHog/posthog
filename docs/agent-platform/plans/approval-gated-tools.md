# Design — control flows / approval-gated tool use

**Status:** draft / open questions. **Owner:** ben.

This is `_TODO.md` item #3. It extends `AgentSpec` so an author can mark
individual tool calls as "requires approval". When the model tries to
invoke one, the session parks; an approval lands via either a PostHog UI
flow or an authorized MCP path; the session resumes with the approved
args (possibly edited by the approver). Builds on the
[long-running-sessions](long-running-sessions.md) lifecycle.

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
2. The runner intercepts the model's tool invocation **before**
   dispatching it. The args are captured; the session parks in `waiting`;
   a `PendingApproval` row is created.
3. The approval surface (UI / MCP) shows: agent identity, session
   context, tool id + description, the model's proposed args, free-form
   reasoning (if the model added any). The approver can:
   - **Approve as-is** — tool runs with the model's exact args.
   - **Approve with edits** — approver modifies args, tool runs with the
     edited args. The edit is part of the audit record.
   - **Reject with reason** — tool result becomes a synthetic error
     message back to the model containing the reason; the session
     unparks and the model decides what to do next (typically:
     apologize, ask a clarifying question, give up).
4. On approval, the session unparks (waiting → queued). The runner
   resumes mid-turn: the in-flight tool call now executes with the
   approved (possibly edited) args. The model sees a normal tool result.

Crucially, the model is **not told** whether the call required approval.
The contract from the model's perspective is "I called the tool, I got a
result (or an error)". This keeps tools composable and the model's
mental model simple. The author declares the policy; the platform
enforces it transparently.

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
      // { approvers: ["session_owner"], allow_edit: true, ttl_ms: 86400000 }.
      "approval_policy": {
        // Who is allowed to approve. See §6.
        //   "session_owner" — the principal that initiated the session
        //   "agent_owner"   — the user who authored the agent
        //   "team_members"  — any active member of the agent's team
        //   "org_admins"    — any org-level admin
        // List is OR'd. First listed wins for default routing UX.
        "approvers": ["session_owner", "team_members"],

        // Can the approver edit args before approval? Default true.
        "allow_edit": true,

        // How long a PendingApproval can sit before auto-rejecting and
        // returning an error to the model. Default: 24h.
        // Past this, runner gets a synthetic "approval_expired" error.
        "ttl_ms": 86400000,
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

## 4. State machine + tool dispatch

### 4.1 New dispatch outcome

`ToolDispatchOutcome` in `services/agent-runner/src/loop/tool-dispatch.ts`
gains a new variant alongside `ok | error | suspend | end`:

```typescript
export type ToolDispatchOutcome =
  | { kind: 'ok'; result: unknown }
  | { kind: 'error'; message: string }
  | { kind: 'suspend'; prompt: string }
  | { kind: 'end'; summary?: string }
  // NEW
  | { kind: 'pending_approval'; approval_id: string }
```

`dispatchTool` checks the resolved spec's `requires_approval` flag
**before** invoking the underlying handler. If set, it persists a
`PendingApproval` row, returns `{ kind: 'pending_approval', approval_id }`,
and never touches the tool. The runner translates this to the same
`state: 'waiting'` outcome as `suspend`, with metadata pointing at the
approval row.

### 4.2 State transitions (per `long-running-sessions.md` §3 wording)

```text
running → waiting           : approval-gated tool intercepted
waiting → queued            : approval lands (approved or rejected)
                              — pending_inputs gets the synthetic tool_result
waiting → failed            : approval ttl elapsed; runner emits error
                              and the model gets one chance to recover
```

Approvals park in **`waiting`**, never `suspended`. Per the long-running
plan's §10: approvals shouldn't compact, since the approver sees a UI
that shows the agent's recent context, and that context must be intact
until the approval lands. The janitor's `compact_after_ms` skip rule:
sessions with an open `PendingApproval` are exempt from compaction.

### 4.3 The runner intercept

The dispatcher already returns control-flow signals to the turn loop
(`run-turn.ts`). Adding `pending_approval` is a small change:

- `dispatch-one.ts` checks `toolRef.requires_approval` at the top of
  `dispatchOne`, writes a `PendingApproval` row keyed by
  `(session_id, turn_index, tool_call_id, tool_name, proposed_args)`,
  returns the new outcome.
- `run-turn.ts` treats `pending_approval` like `suspend`: persists
  partial conversation state (the assistant message with the tool_call
  is saved, but no `tool_result` yet), flips state to `waiting`, emits a
  `waiting` event with `reason: 'pending_approval'`.

### 4.4 Wake mechanics

Mirrors the existing `external_key` wake path
(`services/agent-ingress/src/enqueue/enqueue.ts`):

1. Approver decides via UI/MCP. The approval API resolves the
   `PendingApproval` row → writes the synthetic `tool_result` message
   into `pending_inputs` → updates session state `waiting → queued`.
2. Runner picks up the session. At turn start it drains
   `pending_inputs` into `conversation` (same code path as `/send`
   today, lines 144–147 of `run-turn.ts`). The model now sees the
   tool_result and continues the turn.

The synthetic tool_result shape:

```jsonc
// approve
{ "role": "tool", "tool_call_id": "...", "content": "<actual tool result JSON>" }

// reject
{
  "role": "tool",
  "tool_call_id": "...",
  "content": "{\"error\": \"approval_rejected\", \"reason\": \"<approver reason>\"}"
}

// expired
{
  "role": "tool",
  "tool_call_id": "...",
  "content": "{\"error\": \"approval_expired\", \"reason\": \"no approver responded within 24h\"}"
}
```

Importantly, on **approve**, the runner re-dispatches the tool with
the approved args and writes the **real** result into `pending_inputs`.
The model never sees a synthetic shape; it sees a normal tool result.
On **reject/expired**, the model gets the synthetic error and decides
its next move.

## 5. PendingApproval storage

New table (or row on existing `agent_session` JSONB — see open
question #4). Tentative schema:

```sql
CREATE TABLE agent_pending_approval (
    id              UUID PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES agent_session(id) ON DELETE CASCADE,
    team_id         BIGINT NOT NULL,
    tool_call_id    TEXT NOT NULL,
    tool_name       TEXT NOT NULL,
    proposed_args   JSONB NOT NULL,
    -- approvers allowed to act on this row, resolved at park time
    -- ("session_owner: <uuid>", "team:<id>:members", "team:<id>:admins")
    approver_scope  JSONB NOT NULL,
    state           TEXT NOT NULL CHECK (state IN ('pending', 'approved', 'rejected', 'expired')),
    decision_by     UUID NULL,        -- principal id when decided
    decision_at     TIMESTAMP NULL,
    decision_reason TEXT NULL,
    decided_args    JSONB NULL,       -- present only if approver edited args
    created_at      TIMESTAMP NOT NULL DEFAULT now(),
    expires_at      TIMESTAMP NOT NULL,
    UNIQUE (session_id, tool_call_id)
);
CREATE INDEX ON agent_pending_approval (state, expires_at);
CREATE INDEX ON agent_pending_approval (team_id, state, created_at DESC);
```

Lives in the agent-platform DB (same DB as `agent_session`). `team_id`
is denormalized from the session for fast index-only listing per the
[CLAUDE.md tenant-isolation rule](../../../CLAUDE.md).

## 6. Authorization — who can approve

Two layers:

**a. Spec-declared `approvers` list.** Resolved at park time into
`approver_scope` on the row. Example: `["session_owner", "team_members"]`
on a session initiated by user U in team T resolves to
`[{ kind: "principal", id: U }, { kind: "team_members", team_id: T }]`.

**b. Approval API check.** When the approval lands (UI or MCP), the
caller's principal is checked against `approver_scope`. Reuses the
session's existing principal-resolution (strict-principal already
enforces sender identity on `/send`).

Conflict modes:

- `session_owner` is the initiating principal — i.e. the user whose
  `/send` started the session. For Slack-triggered sessions, that's the
  Slack-mapped PostHog user. For webhook triggers, the principal is
  whoever owns the webhook secret.
- `agent_owner` is the user listed as `AgentApplication.created_by`. For
  agents created via the authoring MCP, this is the authoring user.
- `team_members` / `org_admins` use the existing PostHog ACL: any
  active membership row counts. **No** elevation across teams without
  the `per-session access elevation` (`_TODO` #5) flow first.

Audit: every approval/rejection writes to the platform's existing
activity log (`activity-logging-expert` agent's territory) with
`action: approve_tool_call` / `reject_tool_call`, `target: session_id`,
`detail: { tool_name, decided_args, reason }`.

## 7. Approval surfaces

### 7.1 PostHog UI

New tab on the session detail page: **"Pending approvals"**. Lists each
`pending` approval row with:

- Agent identity + revision link
- Originating trigger (Slack thread? webhook? UI?)
- Recent conversation excerpt (last ~5 turns)
- Tool id + description (pulled from the tool registry)
- Proposed args, editable JSON view
- `Approve` / `Reject` buttons + reason textbox

On submit, calls `POST /agent-sessions/:id/approvals/:approvalId` with
`{ decision, edited_args?, reason? }`. The endpoint runs the
authorization check (§6), updates the row, runs the unpark path (§4.4),
returns 200.

Notifications: each `pending_approval` event fires a notification (via
the platform's notification skill — see `sending-notifications`) to
each principal in `approver_scope`. The notification deep-links to the
approval UI. TTL warnings (`expires_at - 1h`) re-notify if still
pending.

### 7.2 MCP path

New MCP tool: `agent-platform-list-pending-approvals` and
`agent-platform-decide-approval`.

- `list_pending_approvals(filter?: { session_id?, tool_name? })` —
  returns approvals visible to the calling principal.
- `decide_approval(approval_id, decision, edited_args?, reason?)` —
  same endpoint as the UI, same auth check.

This lets an external agent (a "reviewer agent") triage approvals
programmatically. Critically, the reviewer agent is **not** the agent
whose call is being approved — that would be a self-approval loop. The
authorization check rejects approvals where the calling principal is
the same agent's session principal. (Self-approval requires explicit
spec opt-in; see §9 #5.)

## 8. Composition with `meta-ask-for-input`

Both park in `waiting`. The runner needs to distinguish them so the
unpark path picks the right behavior:

- `session.waiting_reason: 'ask_for_input' | 'pending_approval' | 'long_running' | ...`
  — new field on the session row.
- Wake-event handlers branch on `waiting_reason`:
  - `ask_for_input` — the next `/send` becomes the user's reply.
  - `pending_approval` — `/send` is **rejected** with 409 (the session
    isn't accepting free-form input right now); only the approval API
    can advance it.
  - `long_running` — `/send` accepted as normal.

This prevents accidental "the user typed something in Slack while an
approval was pending" → the model interprets the typed message as the
approval. The user sees: "this session is waiting on approval, please
use the approval link". (The notification surface from §7 makes this
obvious.)

Side-effect: an agent can _combine_ both. Model calls
`meta-ask-for-input("Want me to delete team 42?")`. User says "yes".
Model then calls `team-delete(team_id=42)`. The team-delete still
parks for approval if the spec says so — even though the user already
said yes informally, the approval gate is a separate, audited step. The
spec author decides whether the gate is redundant; if so, they don't
mark the tool as `requires_approval` and rely on `ask_for_input` alone.

## 9. Open questions

1. **Per-args-pattern policy.** v0 is per-tool: any invocation of
   `team-delete` parks. Real use cases are finer-grained — "approve
   `insight-create` for read-only insights, gate destructive variants".
   Probable v1: extend `approval_policy` with `match: { args_jsonpath: ... }`
   evaluated at intercept time. Defer until we have ≥2 agents asking
   for it.
2. **Auto-approval rules.** Mirror image: "approve any `insight-create`
   where `team_id == owner_team`". Same `match:` schema as #1, with
   `action: "auto_approve"` instead of `"require_approval"`. Useful for
   reducing approver fatigue. Defer.
3. **MCP-tool approval gating.** Per §3, `spec.mcps[]` tools aren't
   listed individually in spec. Need a `mcp_approvals` policy keyed by
   `(mcp_id, tool_name_glob)`. Probably a v1 follow-up; v0 only gates
   tools that appear in `tools[]`.
4. **Storage shape — row vs JSONB.** New table `agent_pending_approval`
   (§5) keeps queries fast and the session row small. Alternative:
   embed in session JSONB as `session.pending_approval`. Single-row
   means simpler atomic writes but adds JSONB churn on every approval
   decision. Going with the table for clean indexing. Revisit if write
   volume is low.
5. **Self-approval.** A "reviewer agent" calling the MCP approval tool
   on its own session is auto-rejected. But there's a legitimate case:
   an authoring AI test-running its own agent in a dry-run sandbox
   should auto-approve to keep tests automatic. Spec opt-in:
   `approval_policy.allow_self_approval: true`. Only meaningful when
   the agent's principal _is_ the approver scope (rare). Defer to v1.
6. **Approver edits and audit.** When approver edits args, the diff
   between `proposed_args` and `decided_args` is the most important
   audit signal — surface it prominently in the activity log and the
   session timeline.
7. **Notification dedupe.** Multiple principals in `approver_scope`
   means multiple notifications per approval. First-to-act resolves the
   row; the others should see "already decided" in the UI rather than 404. Easy — the list endpoint filters by state.
8. **Edit beyond schema.** What if the approver edits args into a shape
   the tool's input schema rejects? Server-side: re-validate
   `decided_args` against the tool's Zod schema; reject the approval
   submission with a 422. UI: surface schema errors inline before
   submit.
9. **End-of-turn vs mid-turn approval.** Today's model providers may
   return multiple tool calls in one assistant message. If two of those
   are approval-gated, do we park on the first and re-run the model on
   resume (losing the other tool calls), or batch them into one
   approval surface? Probably batch: one `PendingApproval` row per
   `tool_call_id`, all flagged on park; approver sees them as a group;
   all must decide before the session resumes. Worth a follow-up
   prototype.
10. **Composition with long-running `suspended`.** A long-running
    session in `suspended` that the model wakes and then immediately
    invokes an approval-gated tool: rehydrate, intercept, park _back_
    into `waiting` (not `suspended`). The intermediate compaction is
    fine; we don't re-compact during the approval window.

## 10. Rollout

This is additive — disabled by default per tool. Phases:

**v0** (foundation):

- Add `ToolRef.requires_approval` + `approval_policy` to
  `services/agent-shared/src/spec/spec.ts`. Default false.
- Schema migration: new `agent_pending_approval` table.
- Add `pending_approval` outcome + intercept in runner dispatch.
- Add `waiting_reason` field on `agent_session`.
- Add `POST /agent-sessions/:id/approvals/:approvalId` endpoint
  (Django side, agent-ingress).
- Activity-log: register `approve_tool_call` / `reject_tool_call`.
- Existing agents see zero behavior change.

**v1** (first real users):

- Pick one internal agent — the ops / infra-mutating one — and gate
  one destructive tool. Approver is the agent owner.
- Build the session-detail "Pending approvals" tab in the PostHog UI.
- Wire notifications via the existing skill.
- Watch: false-positive rate (approver always says yes →
  `requires_approval` is wrong), expiry rate (approvers asleep at the
  wheel), edit rate (signals the model proposes bad args).

**v2** (broad availability + MCP):

- Expose `requires_approval` in the authoring wizard / MCP YAML
  descriptions.
- Document approval-gating in the authoring skill.
- Ship the MCP approval tools (`list_pending_approvals`,
  `decide_approval`).
- Per-args-pattern policy if at least two agents are asking for it
  (open q #1).

## 11. Dependencies + what this enables

**Depends on:**

- `long-running-sessions.md` — the `waiting → queued` wake mechanism
  and the `compact_after_ms` skip rule for sessions with open
  approvals.

**Enables / interacts with:**

- `_TODO` #4 (rate limiting) — pending approvals don't count against
  the concurrent-running cap (they're waiting) but probably _should_
  count against a separate "pending approvals per team" budget so a
  runaway agent can't flood approvers.
- `_TODO` #5 (per-session access elevation) — when an unauthorized
  principal tries to approve, the platform can surface the elevation
  flow ("you're not in `approver_scope`; ask <session_owner> to grant
  you approval rights on this session").
- `agent-authoring-flow.md` — the authoring AI should reason about
  which tools to gate when drafting the spec. The reference authoring
  skill should include heuristics: "tools whose name contains
  `delete`, `remove`, `cancel`, `send` warrant `requires_approval` by
  default unless the author explicitly opts out".
- `self-healing-agents` (future plan) — false-positive / expiry /
  edit-rate signals from approvals are exactly the kind of feedback a
  self-healing agent could use to refine its tool args before
  proposing them.
