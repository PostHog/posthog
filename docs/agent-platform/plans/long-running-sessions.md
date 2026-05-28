# Design — long-running sessions, explicit resume, and context compaction

**Status:** draft / open questions. **Owner:** ben.

This is the foundational Phase A plan from `_TODO.md`. It nails the session
state machine so the rest of the queue (rate limiting, approval-gated tool
use, per-session access elevation) has a stable shape to build on.

## 1. Problem

Today's session lifecycle:

```text
queued → running → (waiting → queued)* → completed | failed
```

- `waiting` exists **only** as the parked state after
  `@posthog/meta-ask-for-input`. The model decides to suspend; the session
  unparks when a `/send` arrives matching the session's `external_key`.
- The janitor fails any `waiting` session past `stuckWaitingThresholdMs`
  (default 24h). There is no way for an agent to say "I'll watch this
  thread for a week" — the next sweep nukes it.
- `conversation` JSONB grows unbounded with every turn. A long-running
  session eventually drags megabytes through every `claim()` /
  `update()`. The runner doesn't truncate.
- "Has my user replied yet?" is the only resume signal. There's no way
  to schedule a wake-up, no way to react to an external event, no
  way for the _author_ to declare the agent stays alive longer than
  one model-driven park.

The user-visible features this blocks:

- A "Slack assistant" that watches a thread for the whole sprint, not
  one prompt-and-reply cycle.
- A "weekly digest" agent that wakes itself on a cron.
- A "code-review agent" that posts a draft, waits for the human's
  approval (TODO #3), then continues — but might wait days.
- An "incident-response" agent that has to stay coherent across a
  multi-day investigation without re-explaining context from scratch
  each time.

## 2. What "resumable session" precisely means

A resumable session is one that:

1. Has an **explicit, author-declared resumability config** (spec field).
2. Survives in `waiting` state beyond the global janitor TTL — up to the
   per-agent TTL declared in spec.
3. Maintains a **compacted conversation** so resumes don't drag every
   historical message into context.
4. Has a **deterministic reopen contract** — a trigger (Slack reply,
   webhook, cron tick) can target it without ambiguity.
5. Can be deliberately ended by the model (`end_session`), by the
   janitor (per-agent TTL hit), or by the user (cancel).

Existing `ask_for_input` keeps working unchanged — it's the short-form
case. The new shape generalizes to long-form.

## 3. State machine additions

Today's states stay; we add two and tighten the contract on `waiting`:

```text
queued        — picked up by the next runner with capacity
running       — claimed; mid-turn
waiting       — parked, awaiting a wake event (any of: user reply,
                approval, cron tick, external webhook)
suspended     — NEW. parked + compacted. lives until per-agent TTL.
                unpacks back to waiting on a wake.
completed     — terminal. model called end_session OR per-agent
                completion policy said "done".
failed        — terminal. runner crashed past poison-pill threshold,
                or hit max_wall_seconds, or compaction blew up.
```

Why two parked states? `waiting` keeps its meaning as "actively parked,
expecting a wake imminently — full context retained for fast resume".
`suspended` is "parked indefinitely — context compacted, wake will
require a rehydrate step before the next turn runs".

Transitions:

- `waiting → suspended` — fired by janitor sweep when a `waiting`
  session ages past `compact_after_ms` (per-agent config, default 1h).
- `suspended → waiting` — fired by a wake event. Runner rehydrates
  compacted history into a fresh context window (see §5), claims the
  row, runs the next turn.
- `waiting | suspended → completed` — model decides, user cancels, or
  per-agent `max_resume_age_ms` hits.

The sweep policy that fails stuck waiting rows today (`stuckWaitingMs`)
becomes the **upper bound** — applied only when the agent's spec says
the session isn't resumable. For resumable agents the sweep uses
`max_resume_age_ms` from spec.

## 4. Spec config

New section on `AgentSpec`:

```jsonc
{
  "resume": {
    // Whether this agent's sessions can outlive a single turn cycle.
    // false (default) preserves today's behavior: waiting > 24h → failed.
    "enabled": true,

    // Compact `waiting` sessions after this. Past this age the
    // session moves to `suspended` and its conversation is compacted.
    // Default: 3600000 (1h).
    "compact_after_ms": 3600000,

    // Hard ceiling. Past this, sweep marks the session completed
    // (graceful) or failed (with reason="max_resume_age").
    // Default: 604800000 (7 days).
    "max_resume_age_ms": 604800000,

    // Per-agent cap on simultaneously-suspended sessions. Helps the
    // rate-limit plan (`_TODO` #4) bound storage growth.
    // null = no cap.
    "max_suspended_sessions": 100,

    // Compaction strategy. See §5.
    "compaction": {
      "strategy": "summarize", // "summarize" | "window" | "none"
      "keep_recent_turns": 6, // for "window"; ignored for others
      "summary_model": "anthropic/claude-haiku-4-5", // for "summarize"
    },

    // When `external_key` reopens an old session, what's the freshness
    // policy? "always" reuses the most-recent matching session
    // regardless of age; "within_resume_window" only if it's not
    // past `max_resume_age_ms`; "never" creates a new session for
    // every trigger. Default: "within_resume_window".
    "external_key_reuse": "within_resume_window",
  },
}
```

Spec validation runs at freeze time (per `agent-authoring-flow.md` §3).
Backwards-compatible default: `resume.enabled = false` means today's
behavior. Existing agents continue working unchanged.

## 5. Context compaction

The compaction step converts a long `conversation` into a smaller
representation that fits in the model's working context while preserving
meaning. Three strategies:

### "window" — sliding window

Keep the last N turns verbatim. Drop everything older. Cheap, lossy.
Suitable for agents where old context is genuinely stale (e.g. a Slack
thread that asks unrelated questions over time).

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
- Re-compact (if the conversation grows again after wake, the next
  compaction summarizes the synthetic summary + new turns).

### "none" — refuse to compact

Spec opts out. Sessions never move past `waiting`. Useful for short
agents that explicitly want full fidelity OR for testing /
self-healing agents that need raw traces. Combined with a short
`max_resume_age_ms` this is fine.

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
shape as `reapStuckRunning`.

Failure handling: if compaction itself fails (model error, network),
mark `compaction_meta.last_error` on the row, retry on the next sweep up
to `MAX_RETRIES` (reuse the poison-pill counter). After threshold,
demote to `window` strategy as a fallback.

## 6. Trigger-side contract — reopening an old session

Today: trigger → `findByExternalKey(application_id, external_key)`. If
there's an active session, append to `pending_inputs` and re-queue. If
not, create a new session.

With resumable agents this needs the `external_key_reuse` policy:

- `"always"` — match any session with the key, regardless of state. If
  the matched session is in `suspended`, the ingress fires a wake event:
  the row's state flips to `queued`, a wake-up note is added to
  `pending_inputs` along with the new user message, and the runner picks
  it up. If the session is `completed` or `failed`, we re-open it
  (transition `completed → queued`) with the prior conversation +
  the new user message.
- `"within_resume_window"` — same as `"always"` for sessions inside
  `max_resume_age_ms`. Past that age, the matched session is treated as
  closed and a new session is created. The old session's `external_key`
  is cleared on the next sweep so the new session "owns" the key.
- `"never"` — every trigger creates a new session. Useful for stateless
  agents.

When the runner picks up a `queued` session that was previously
`suspended`, it rehydrates: reads `compacted_prefix` + `conversation`,
builds the next-turn context, runs. No extra work for the model —
compaction is transparent.

### Cron / scheduled wake (out of scope here, but the hook lives here)

A separate plan covers cron triggers, but the wake mechanism is the
same: the cron emits a synthetic "wake" pending_input, transitions the
row to queued, runner takes it. So this design accommodates it without
extra surgery.

## 7. Visibility / observability

What gets exposed:

- **Session detail (janitor `/sessions/:id`)**: includes `compaction_meta`
  - `compacted_prefix` so debugging tools see what was dropped.
- **Authoring API**: a new
  `agent-applications-sessions-suspended-list` _(to be added per
  `agent-authoring-flow.md` §3)_ so the MCP can show "your agent has 17
  suspended sessions; here are the most-recent".
- **Sweep result**: extended from
  `{ requeued, poisoned, failed }` to also include
  `{ compacted, awoken, max_age_completed }`.

## 8. Open questions

1. **Storage**: compacted-prefix + retained conversation are both on the
   session row JSONB. For a 7-day session with multiple compaction
   cycles, the row grows linearly in the summaries. Cap it? Roll up
   summaries into a single new summary past N? Probably yes — second
   summarization pass when the prefix itself exceeds N tokens.
2. **Tool result lifecycle**: today tool results live as messages in
   `conversation`. After compaction the synthetic summary contains the
   _gist_ but the model can't re-inspect a specific old tool_result.
   Probably fine — if it mattered, the model would have surfaced it
   in the conversation. Document the limitation.
3. **External-key reuse + cross-team safety**: today `external_key` is
   scoped to `(application_id, external_key)`. A reopened session
   inherits its original `team_id`. Ensure the wake-event ingress
   re-checks team membership of the _new_ sender so a team change
   doesn't smuggle access.
4. **Pricing / quotas**: compaction is a model call per sweep per
   long-running session. At 1000 sessions × hourly compaction × 1 Haiku
   call, that's 24K compaction calls/day — measurable but cheap. Worth
   surfacing in the team's LLM analytics so we can see the cost. Hard
   cap?
5. **Wake notification UX**: when an old Slack thread is woken, the
   agent's next message arrives in the thread. The user sees "this
   thread woke up after 5 days". Do we want a synthetic "👋 still here
   — let me catch up on what's changed" message OR does the agent
   author decide via spec/skill? Defer to the author.
6. **Replay vs compact ordering**: `resumable-conversations.md` (the
   read-side, B8) wants to show users old session traces. If we compact
   the live row but preserve the full audit in CH `log_entries`, the
   "show me what happened" path reads CH, not the row. Reconcile with
   the four questions in `resumable-conversations.md`.
7. **Per-session opt-out** of compaction: a model might tag a session
   as "do not compact" (e.g. an incident-response thread where
   completeness matters more than efficiency). Probably a `compact: false`
   field on the session row that the model can set via a new meta tool
   `@posthog/session-pin-context`. Designed in but punted to a follow-up.

## 9. Rollout

This is additive — disabled by default per agent. Rollout phases:

**v0** (foundation):

- Add `resume.*` spec fields. Default `enabled: false`. Validation
  enforces sane ranges.
- Schema migration: add `compacted_prefix JSONB`, `compaction_meta JSONB`
  to `agent_session`. Both nullable.
- Janitor sweep extended: `compactAged` + `wakeFromSuspended` policies
  added alongside the existing reap.
- New session state `suspended`. State machine updated in `spec.ts`.
- Existing agents see no behavior change.

**v1** (first real users):

- Pick one internal agent (probably the @agent-builder Slack bot once
  it lands, or the canonical "research assistant" template) and flip
  `resume.enabled: true` with `compaction.strategy: summarize`.
- Watch CH for compaction call cost; surface in LLM analytics.
- Adjust defaults if needed.

**v2** (broad availability):

- Expose `resume.*` in the authoring wizard / MCP YAML descriptions.
- Document the trade-offs in the authoring skill (this design's §5,
  abbreviated, ends up in `@posthog/authoring`).
- Add the suspended-sessions endpoint.

## 10. What this enables for the other plans

- **`_TODO` #3 — control flows / approval-gated tool use**: reuses the
  `waiting → wake event → resume` lifecycle. Approval flow parks a
  session in `waiting` (not `suspended` — approvals shouldn't compact),
  the UI / MCP fires a wake when the approval lands.
- **`_TODO` #4 — rate limiting + queue policy**: hooks
  `max_suspended_sessions` into the queue admission policy.
- **`_TODO` #6 — per-session access elevation**: elevation events are
  just wakes with an ACL-mutation pending_input.
- **`agent-authoring-flow.md` test-run infrastructure**: test sessions
  never compact (`compaction.strategy: none`) so traces stay clean for
  self-evaluation.
- **`resumable-conversations.md` (B8 read side)**: the source-of-truth
  question is resolved — `conversation` JSONB is canonical for the live
  state; CH is the audit log for display.
