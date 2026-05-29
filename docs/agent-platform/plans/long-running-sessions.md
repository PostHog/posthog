# Design — long-running sessions, explicit resume, and context compaction

**Status:** refreshed against the post-session-restart state machine. **Owner:** dylan (workstream W1, after B.1).

This is the foundational Phase A plan from `_TODO.md`. It nails the session
state machine so the rest of the queue (rate limiting, approval-gated tool
use, per-session access elevation) has a stable shape to build on.

> **Note on history.** An earlier draft of this plan was written against the
> pre-cutover state machine that included a `waiting` state. That state was
> removed when [`session-restart-and-state-machine.md`](session-restart-and-state-machine.md)
> shipped — `completed` is now the open-but-idle state. This plan has been
> rewritten against the post-cutover shape: the new parked-and-cold state is
> called `suspended` and sits alongside (not in place of) `completed`.

## 1. Problem

Today's session lifecycle, after the session-restart redesign:

```text
queued → running → (completed → queued)* → closed | failed
```

- `completed` is the **open** end-of-turn state. `/send` re-queues; an
  `external_key` match resumes (subject to the B.1 ACL check). The janitor
  auto-closes `completed` rows older than `idleCompletedThresholdMs`
  (default 24h) to keep the queue tidy.
- There is no way for an agent to say "I'll watch this thread for a week" —
  the 24h sweep is global, unconditional, and applies regardless of the
  agent's profile. A Slack assistant for a multi-week project gets
  silently closed every night.
- `conversation` JSONB grows unbounded with every turn. A long-running
  session eventually drags megabytes through every `claim()` / `update()`.
  The runner doesn't truncate.
- "Has the user replied via `external_key`?" is effectively the only resume
  signal. There's no way to schedule a wake-up, no way to react to an
  external event, no way for the author to declare the agent should
  remain reachable beyond the global TTL.

The user-visible features this blocks:

- A "Slack assistant" that watches a thread for a whole sprint, not just
  the global 24h window.
- A "weekly digest" agent that wakes itself on a cron — sleeps cold the
  rest of the time and wakes with the right context.
- A "code-review agent" that posts a draft, waits for approval (B.2), then
  continues — but might wait days.
- An "incident-response" agent that has to stay coherent across a
  multi-day investigation without re-explaining context from scratch.

## 2. What "resumable session" precisely means

A resumable session is one that:

1. Has an **explicit, author-declared resumability config** (spec field).
2. Survives beyond the global 24h `idleCompletedThresholdMs` — up to the
   per-agent TTL declared in spec.
3. Maintains a **compacted conversation** so resumes don't drag every
   historical message into context.
4. Has a **deterministic reopen contract** — a trigger (Slack reply,
   webhook with `x-external-key`, chat `/send`, cron tick) can target it
   without ambiguity.
5. Can be deliberately ended by the model (`@posthog/meta-end-session`),
   by the janitor (per-agent TTL hit), or by the user (`/cancel`).

Non-resumable agents keep today's exact behaviour: end of turn lands at
`completed`, sweep closes them at 24h. The new lifecycle is opt-in and
backwards compatible.

## 3. State machine additions

Today's five states stay; we add one parked-cold state alongside
`completed`:

```text
queued     — picked up by the next runner with capacity.
running    — claimed; mid-turn.
completed  — parked + hot. End of turn. Full conversation in memory;
             /send and external_key match re-queue immediately. Open by
             default — auto-closed at idleCompletedThresholdMs unless
             the agent opts into resume.
suspended  — NEW. parked + cold. Compacted: `compacted_prefix` populated,
             `conversation` trimmed. Lives until per-agent
             `max_resume_age_ms`. Wake event flips to `queued` and the
             runner rehydrates at claim time.
closed     — terminal. meta-end-session, sweep auto-close, or
             max_resume_age hit.
failed     — terminal. Runner crashed past poison-pill threshold,
             max_wall_seconds, /cancel, or compaction itself blew up
             past retry budget.
```

Why two parked states? `completed` keeps its session-restart meaning —
hot, full context, instant resume, the default end-of-turn home.
`suspended` is "we don't expect a wake imminently; compress to save row
size, accept a rehydrate cost on the next wake". A clean split:
`completed` = expected to wake soon; `suspended` = might wake never.

Transitions added or changed:

- `completed → suspended` — janitor sweep when a `completed` row ages
  past `spec.resume.compact_after_ms` (default 1h). The compaction step
  runs synchronously inside the sweep (see §5).
- `suspended → queued` — any wake event: external_key match, `/send`, a
  cron tick, an approval landing, an elevation grant. The runner picks
  up the queued row, sees `compacted_prefix` is non-null, and assembles
  the next-turn context from `compacted_prefix + conversation + pending_inputs`.
- `completed → closed` — unchanged for non-resumable agents
  (`idleCompletedThresholdMs`, default 24h). For resumable agents the
  sweep skips this transition entirely — the lifecycle is
  `completed → suspended → … → closed`.
- `suspended → closed` — sweep when age past `spec.resume.max_resume_age_ms`
  (default 7d). Terminal via the same "cleanly idle, time's up" reasoning
  as the current `completed → closed` sweep.

What the runner has to learn:

- At claim time, if `compacted_prefix` is non-null, prepend the summary
  (or window) into the model context as a synthetic system message before
  draining `pending_inputs` and `conversation` into the turn. This is
  the rehydrate path; it's purely additive — non-resumable agents never
  carry `compacted_prefix` and the codepath is a no-op.

## 4. Spec config

New section on `AgentSpec`:

```jsonc
{
  "resume": {
    // Whether this agent's sessions can outlive the global completed-sweep
    // TTL. false (default) preserves today's behaviour: completed > 24h →
    // closed, no compaction, no suspension.
    "enabled": true,

    // Move `completed` sessions to `suspended` after this. Past this age
    // the row is compacted (per `compaction.strategy`) and parked cold.
    // Default: 3600000 (1h). Should be ≥ idleCompletedThresholdMs in
    // practice, but the sweep handles either order safely.
    "compact_after_ms": 3600000,

    // Hard ceiling on the suspended state. Past this, sweep marks the
    // session `closed` (graceful) or `failed` (with reason="max_resume_age"
    // on a compaction-retry blow-up).
    // Default: 604800000 (7 days).
    "max_resume_age_ms": 604800000,

    // Per-agent cap on simultaneously-suspended sessions. Hooks into the
    // rate-limit plan (`rate-limiting-sessions.md`) so a misbehaving
    // long-running agent can't fill the queue table with cold rows.
    // null = no cap.
    "max_suspended_sessions": 100,

    // Compaction strategy. See §5.
    "compaction": {
      "strategy": "summarize", // "summarize" | "window" | "none"
      "keep_recent_turns": 6, // for "window"; ignored for others
      "summary_model": "anthropic/claude-haiku-4-5", // for "summarize"
    },
  },
}
```

Spec validation runs at freeze time. Backwards-compatible default:
`resume.enabled = false` means today's behaviour. Existing agents keep
working unchanged.

Note: the original draft of this plan carried an `external_key_reuse`
policy with values `"always" | "within_resume_window" | "never"`. With
the session-restart state machine the policy is now implicit:

- `completed` / `suspended` → resume (subject to B.1 ACL check).
- `closed` with `allow_restart` trigger config → reopen.
- `closed` (default) / `failed` → fresh session.

There's nothing left for `external_key_reuse` to express. Dropping it.

## 5. Context compaction

The compaction step converts a long `conversation` into a smaller
representation that fits in the model's working context while preserving
meaning. Three strategies:

### "window" — sliding window

Keep the last N turns verbatim. Drop everything older. Cheap, lossy.
Suitable for agents where old context is genuinely stale (a Slack thread
that asks unrelated questions over time).

Stored on the session row:

```jsonc
{
  "conversation": [
    /* last N turns */
  ],
  "compacted_prefix": null,
  "compaction_meta": { "strategy": "window", "kept_turns": 6, "dropped_turns": 42 },
}
```

### "summarize" — LLM-condensed prefix

Walk the older turns, ask a cheap model (`summary_model`, default Haiku)
to produce a 1-2 paragraph summary. Replace those turns with one
synthetic system message:

```text
[Conversation summary: <summary text>. Earlier turns: 42. Time span: 5 days.]
```

Plus the recent N turns verbatim. Higher quality, costs one model call
per compaction.

Stored:

```jsonc
{
  "conversation": [
    /* synthetic summary as system msg, then last N turns */
  ],
  "compacted_prefix": { "summary": "...", "covered_turns": 42, "summarized_at": "..." },
  "compaction_meta": { "strategy": "summarize", "summary_model": "...", "summary_tokens": 312 },
}
```

The `compacted_prefix` is preserved separately so we can:

- Show the user / authoring AI what was compacted (transparency).
- Re-compact: if the conversation grows again after wake, the next
  compaction summarizes the synthetic summary + new turns.

### "none" — refuse to compact

Spec opts out. Sessions stay at `completed` indefinitely (subject to
`idleCompletedThresholdMs`). Useful for short agents that explicitly
want full fidelity OR for testing / self-healing agents that need raw
traces.

### Choosing a strategy

- Default to `summarize` for `resume.enabled = true`.
- The authoring AI picks based on what the agent does — long-running
  "context-heavy" agents benefit from `summarize`; "stateless after each
  topic" agents are fine with `window`.

### Where compaction runs

Janitor — not the runner. The runner runs turns; the janitor runs
periodic state maintenance. Compaction needs LLM access (for
`summarize`) so the janitor calls the runner's `PiClient` via the same
config the runner uses (or directly, via a small `compact_session`
helper). Adding LLM-call ability to the janitor is one new dependency
but it's the right home — compaction is a background sweep job, same
shape as `reapStuckRunning` / `idleCompletedClose`.

Failure handling: if compaction itself fails (model error, network),
stamp `compaction_meta.last_error` on the row, retry on the next sweep
up to `MAX_RETRIES` (reuse the poison-pill counter). After threshold,
demote to `window` strategy as a fallback. If `window` also fails (it
shouldn't; it's pure JS), fail the session.

## 6. Trigger-side contract — reopening a session

Today's resume path: trigger → `findByExternalKey(application_id, external_key)` →
ACL check (B.1) → append to `pending_inputs` → flip state to `queued`.
That already handles `completed` resumes correctly.

For `suspended` we extend the resume path identically — same external_key
match, same ACL check, same enqueue. The runner's claim picks the row up,
and the only new bit is the rehydrate step in the loop (§3 above). No
trigger-side surgery required.

State-wise the trigger sees:

| Existing state | Result of an external_key match                                       |
| -------------- | --------------------------------------------------------------------- |
| `queued`       | append pending_inputs (existing).                                     |
| `running`      | append pending_inputs (existing).                                     |
| `completed`    | append pending_inputs + `state → queued` (existing).                  |
| `suspended`    | append pending_inputs + `state → queued`. Runner rehydrates at claim. |
| `closed`       | terminal — fresh session unless trigger has `allow_restart`.          |
| `failed`       | terminal — always fresh session.                                      |

### Cron / scheduled wake (handed off to `cron-trigger-scheduler.md`)

Cron is a separate plan, but the wake mechanism is the same: the
scheduler emits a synthetic "wake" pending_input on the cron-trigger
agent's most-recent matching session, flips state to `queued`, and the
runner picks it up. The rehydrate path runs on a suspended row the same
way a Slack-thread wake would. Cron is the strongest motivator for
`suspended` — daily/weekly digests sit cold between fires.

### Approvals (B.2) and elevations (B.1) as wake events

A session parked on a pending approval lives at `completed` per the
session-restart contract. If the approval is slow enough for the
compaction sweep to fire, the row transitions to `suspended` cleanly;
the approval landing later still appends a `pending_input` and queues
the row. Same for an elevation grant landing on a long-suspended Slack
thread. The lifecycle is uniform — anything that produces a
`pending_input` is a valid wake.

## 7. Visibility / observability

What gets exposed:

- **Session detail (janitor `/sessions/:id`)** — includes
  `compaction_meta` + `compacted_prefix` so debugging tools see what was
  dropped.
- **Authoring API** — extend `agent-applications-sessions-list` with a
  `states` filter that includes `suspended` (matches the existing filter
  shape; no new endpoint).
- **Sweep result** — extended from
  `{ requeued, poisoned, closed, expired_approvals }` to also include
  `{ suspended, max_age_closed }`. Both are exported through the janitor's
  existing sweep-metrics path.
- **Bus events** — add `suspended` and `awoken` lifecycle events to
  `SessionEventBus`. SSE consumers that want to render "this session
  went cold for 3 days, here's the catch-up" can listen for `awoken`.

## 8. Open questions

1. **Storage growth on multi-cycle compaction**. A 7-day session with
   multiple wake → re-compact cycles grows linearly in the prefix
   summaries. Cap it? Roll up summaries past N tokens with a second
   summarization pass — yes, but defer the implementation until we see
   real session shapes.
2. **Tool result lifecycle**. Today tool results live as messages in
   `conversation`. After compaction the synthetic summary contains the
   gist but the model can't re-inspect a specific old tool_result.
   Probably fine — if it mattered the model would have surfaced it in
   the conversation. Document the limitation.
3. **Cross-team safety**. External_key is scoped to
   `(application_id, external_key)`. A reopened (suspended → queued)
   session inherits its original `team_id`. B.1's ACL check already
   re-validates the incoming principal at wake time, so a user who lost
   team membership between suspend and wake can't smuggle access. Worth
   an explicit test.
4. **Pricing**. Compaction is a model call per sweep per long-running
   session. At 1000 suspended sessions × hourly recheck × 1 Haiku call,
   that's ~24k compaction calls/day cluster-wide — measurable but
   cheap. Worth surfacing in the team's LLM analytics. Hard cap?
5. **Wake notification UX**. When a 5-day-old thread wakes, the agent's
   next message arrives in the thread. Does the author want a synthetic
   "👋 still here — let me catch up on what's changed" message
   prepended? Defer to the author via spec.
6. **Resumable-conversations read side**. `resumable-conversations.md`
   (B8) wants to show users old session traces. If we compact the live
   row but preserve the full audit in CH `log_entries`, the "show me
   what happened" path reads CH, not the row. Aligned in spec; the
   `compacted_prefix` is the live-state surface, CH is the audit
   surface.
7. **Per-session compaction opt-out**. A model might tag a session as
   "do not compact" (an incident-response thread where completeness
   matters more than efficiency). Probably a `compact: false` field on
   the session row the model can set via a new meta tool
   `@posthog/session-pin-context`. Designed-in but punted to a
   follow-up.
8. **Compaction sweep interval vs `compact_after_ms`**. The sweep ticks
   every `SWEEP_INTERVAL_MS` (default 60s). A `compact_after_ms` of 1h
   means up to a 61-minute lag before a freshly-idle session compacts.
   Acceptable. Don't tighten the sweep just for compaction; the
   amortized cost matters more than the precise transition time.

## 9. Rollout

This is additive — disabled by default per agent. Rollout phases:

**v0** (foundation, code-side):

- Add `resume.*` spec fields. Default `enabled: false`. Validation
  enforces sane ranges and rejects `compact_after_ms > max_resume_age_ms`.
- Schema migration: add `compacted_prefix JSONB`, `compaction_meta JSONB`
  to `agent_session`. Both nullable. Add `suspended` to the state CHECK
  constraint if there is one (today the column is plain TEXT — no change
  needed).
- New session state `suspended`. State machine updated in `spec.ts`
  (`AgentSession.state` literal type).
- Janitor sweep extended with two new policies:
  - `compactAged`: `completed` rows past `spec.resume.compact_after_ms`
    on resume-enabled agents → compact + transition to `suspended`.
  - `maxResumeAgeClose`: `suspended` rows past `spec.resume.max_resume_age_ms`
    → `closed`.
  - Existing `idleCompletedClose` policy only applies when
    `spec.resume.enabled = false`.
- Runner rehydrate step: at claim, if `compacted_prefix` is non-null,
  prepend the synthetic summary into the model context.
- Existing agents see no behaviour change.

**v1** (first real users):

- Pick one internal agent (the @agent-builder Slack bot once it lands,
  or a canonical "research assistant" template) and flip
  `resume.enabled: true` with `compaction.strategy: summarize`.
- Watch CH for compaction call cost; surface in LLM analytics.
- Adjust defaults if needed.

**v2** (broad availability):

- Expose `resume.*` in the authoring AI's spec-shape descriptions.
- Document the trade-offs in the authoring skill (this design's §5,
  abbreviated).
- Add the suspended-sessions filter on the authoring API.

## 10. What this enables for the other plans

- **B.1 per-session-access-elevation**: elevation grants on a suspended
  session wake it via the same `pending_input` path as Slack replies.
  No special handling. B.1 v0 already runs the ACL check on the resume
  path so a wake on a suspended session goes through the same gate.
- **B.2 approval-gated tools**: approvals can park sessions for days.
  Today a session waits at `completed` and the 24h sweep would close it
  before a slow approver could decide. With resume enabled the row
  cleanly transitions to `suspended` instead and the approval landing
  later wakes it.
- **B.3 rate-limiting**: `max_suspended_sessions` hooks into the
  per-agent admission policy so a long-running agent doesn't drown the
  queue table with cold rows. The platform-wide
  `AGENT_PLATFORM_TEAM_MAX_SUSPENDED` env knob layers on top.
- **C.4 resumable-conversations** (B8 read side): the source-of-truth
  question is resolved — `conversation` JSONB is canonical for the live
  state; CH is the audit log for display. The `compacted_prefix`
  documents what was dropped from the live row so the read-side renderer
  can show "earlier turns: see audit log".
- **C.5 cron-trigger-scheduler**: cron-trigger agents are the strongest
  motivator for `suspended` — daily / weekly fires want the row to sit
  cold and wake with the right context. The wake path is identical to
  an externalKey-driven Slack resume.
- **Agent-authoring test infrastructure** (D.1): test sessions never
  compact (`compaction.strategy: none`) so traces stay clean for
  self-evaluation.
