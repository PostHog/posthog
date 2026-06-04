# Design — session failure observability (surface runner errors to authors)

**Status:** plan only, no code yet. **Owner:** dylan.
**Tracking:** [`_ROADMAP.md`](_ROADMAP.md) §C (follow-up).

## Decision (read this first)

Two-layer fix for the load-bearing UX gap "my agent's session failed and
I have no idea why":

- **Layer 1 — push runner-side crash errors through the structured
  `LogSink`** so they appear in the existing session **Logs** tab in
  the agent console. ~5 LOC change in
  `services/agent-runner/src/workers/worker.ts`. No schema work, no UI
  work, no migration. This alone closes the "I can see the session
  failed but the actual error lives in runner stdout I can't access"
  problem for every end-user.
- **Layer 2 — add a `failure_reason` field to `AgentSession`** so the
  session-detail header in the console can render a banner with the
  inline failure context. ~80 LOC across runtime schema, runner write,
  agent_session migration, and console UI. Makes the failure obvious
  at a glance instead of requiring users to dig through the Logs tab.

Ship Layer 1 first. Layer 2 is the UX polish that lands once Layer 1
is in users' hands.

## Problem

When a session crashes in the runner, the catch block at
[`worker.ts:429`](../../../services/agent-runner/src/workers/worker.ts)
calls `sLog.error(...)` with the error message + stack, then updates the
session row to `state: 'failed'`. The session is now terminal.

`sLog` is a pino child logger that writes to runner **stdout only**. The
crash details never reach:

- The structured `LogSink` (Kafka in prod, in-memory in tests). The
  LogSink is the platform's session-attached log stream, surfaced in the
  agent console's per-session **Logs** tab.
- The session row itself. `AgentSession` has no `failure_reason` field —
  only `state: 'failed'`.

End-user experience: open the session in the console, see a red "failed"
badge, nothing else. No banner, no log entry, no "MCP open failed:
invalid apiVersion." The information exists in runner stdout — accessible
only to whoever's running the stack — but the platform's own
observability layer never sees it.

This bit a real user during runtime-MCP smoke testing on this branch:
a misconfigured `X-GitHub-Api-Version` header caused GitHub's MCP server
to reject the open with `bad request: error: invalid apiVersion`. The
operator could see the error in agent-runner stdout because they were
running the stack locally; an end user authoring against a deployed
PostHog had no path to that information at all.

The fix is structural, not a one-off. Any runtime error during the
session lifecycle (sandbox acquire failure, MCP open failure, model
provider error, integration credential miss, tool dispatch failure)
should reach the author through the platform's existing observability
surfaces, not just runner stdout.

## Layer 1 design — wire crashes through LogSink

### Code change

The worker already has `deps.logs: LogSink` (line 110); the LogSink is
constructed at runner boot and threaded through. The catch block at
line 428 needs to push the error into it:

```typescript
} catch (err) {
    const message = (err as Error).message
    const stack = (err as Error).stack
    sLog.error({ err: message, stack }, 'session.crashed')
    // Mirror the crash into the session log stream so the console's
    // Logs tab carries the failure context for the author. The pino
    // logger above is for operator-side debugging; the LogSink is the
    // user-facing observability path.
    await this.deps.logs?.append(session.id, {
        level: 'error',
        msg: 'session.crashed',
        meta: { err: message, stack },
        timestamp: new Date().toISOString(),
    }).catch(() => undefined) // best-effort; logs flush shouldn't block the failure write
    await this.deps.queue.update(session.id, {
        state: 'failed',
        // ... existing fields ...
    })
}
```

LogSink is optional (tests don't always wire it), hence the `?.append`.
The `.catch(() => undefined)` ensures a failing LogSink (Kafka outage,
in-memory sink full) can't strand the session in an inconsistent state
— marking it failed is the load-bearing action.

### Error message sanitization

The crash message goes into the user-visible log stream. Two
considerations:

- **Stack frames may leak internal file paths** (e.g.
  `/Users/dylan/github.com/PostHog/posthog/node_modules/...`). Strip the
  prefix before persisting. Existing pino logs do this via a serializer
  hook; reuse it for the LogSink write.
- **Tokens / secrets may appear in error messages** if a downstream error
  echoed them. The MCP SDK doesn't do this today, but defense in depth:
  scrub anything matching common bearer-token prefixes
  (`xoxb-`, `xoxp-`, `ghp_`, `gho_`, `github_pat_`, `ntn_`, `xapp-`)
  before the LogSink write. Pure regex, ~10 LOC.

### Cost estimate

- `worker.ts` catch block: ~5 LOC
- Token-prefix scrubber + tests: ~30 LOC (lives in
  `services/agent-shared/src/runtime/log-scrubber.ts`)
- New worker test asserting LogSink receives a crash event:
  ~20 LOC in `services/agent-runner/src/workers/worker.test.ts`

~60 LOC total. Single PR.

### What this unlocks

Every runtime crash becomes a structured log entry on the session,
surfaced in the existing console Logs tab. Authors can debug their own
agents end-to-end without operator access to runner stdout. Covers:

- MCP open failures (the canary case that motivated this plan)
- Sandbox acquire failures (capacity, image pull, etc.)
- Model provider errors (rate limit, invalid model, auth)
- Integration credential resolution errors
- Tool dispatch unhandled throws
- Any other unexpected crash path

## Layer 2 design — `failure_reason` on the session row

### Schema change

Add a nullable column + interface field:

```sql
-- migration: 0NNN_agent_session_failure_reason.sql
ALTER TABLE agent_session
  ADD COLUMN failure_reason TEXT NULL;
```

```typescript
// services/agent-shared/src/spec/spec.ts
export interface AgentSession {
  // ... existing fields ...
  /**
   * One-line reason for terminal failure. Set by the worker when the
   * session crashes (MCP open failure, sandbox acquire failure, model
   * provider error, etc.) or by an explicit cancel-with-reason. Null
   * for sessions that completed or are still running. Authors see
   * this rendered as a banner on the session-detail page in the
   * agent console; the full stack lives in the Logs tab (Layer 1).
   *
   * Length-capped at 512 chars to keep the row diff-reviewable and
   * the console rendering predictable. Longer error contexts are
   * preserved in the Logs tab.
   */
  failure_reason: string | null
}
```

### Worker write

```typescript
} catch (err) {
    const message = (err as Error).message
    // ... LogSink write (Layer 1) ...
    await this.deps.queue.update(session.id, {
        state: 'failed',
        failure_reason: truncate(scrubTokens(message), 512),
        // ... existing fields ...
    })
}
```

Same scrubber as Layer 1. Truncate at 512; the Logs tab has the full
context.

### Console rendering

`services/agent-console/app/agents/[slug]/sessions/[sessionId]/` —
session-detail page. When `session.state === 'failed'` and
`session.failure_reason !== null`, render a banner above the
conversation:

```text
┌──────────────────────────────────────────────────────────────┐
│ ⚠ This session failed. <failure_reason verbatim>             │
│ Full details in the Logs tab.                                │
└──────────────────────────────────────────────────────────────┘
```

Banner is dismissable but persists across page loads (it's data, not
UI state). ~40 LOC of TSX + a small banner component.

### Cost estimate

- Django migration: ~10 LOC
- TypeScript schema field + worker write: ~10 LOC
- Console banner component + render in session detail: ~50 LOC
- Updates to OpenAPI generated types (auto)
- Tests: existing worker test from Layer 1 extends; ~20 LOC more in
  console for a story showing the banner

~80 LOC + a one-column migration. Single PR.

### What this unlocks

Authors see the failure reason **inline on the session page** without
clicking into Logs. The two-second debugging loop:

1. See "failed" badge on a session
2. Read the inline banner: "MCP open failed: invalid apiVersion"
3. Patch the spec, freeze, promote, retry

vs. the current loop:

1. See "failed" badge
2. Find the operator running the stack
3. Have them grep runner stdout for the session id
4. Read them the error over Slack

## Token scrubbing — shared helper

Both layers reuse the same scrubber:

```typescript
// services/agent-shared/src/runtime/log-scrubber.ts
const TOKEN_PREFIXES = [
  'xoxb-',
  'xoxp-',
  'xapp-',
  'xoxa-', // slack
  'ghp_',
  'gho_',
  'ghu_',
  'ghs_',
  'github_pat_', // github
  'ntn_', // notion
  'sk-', // openai / generic
  'pat_',
  'lin_api_', // linear
  'Bearer ', // any bearer header that snuck into an error
]

export function scrubTokens(input: string): string {
  let out = input
  for (const prefix of TOKEN_PREFIXES) {
    // Match prefix + non-whitespace chars (the token body), case-insensitive
    // for prefixes that vary in case ("Bearer "). Replace with prefix + ****
    // so the log still shows what KIND of token leaked but not the value.
    const re = new RegExp(prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\S+', 'gi')
    out = out.replace(re, prefix + '****')
  }
  return out
}
```

Tests: each prefix scrubs correctly; no prefix → pass-through; mixed
content with multiple tokens; prefix at start/middle/end of string.
Lives in `services/agent-shared/src/runtime/log-scrubber.test.ts`.

## Open questions

1. **Should the LogSink write include the full stack or just the
   message?** Stack is useful for debugging but bloats the log stream
   and contains internal paths. Recommendation: message in `msg`, stack
   in `meta.stack` (separate field), console renders message only by
   default with an expand-to-show-stack control.
2. **Retroactive sessions** that failed before this lands have no
   `failure_reason`. UI should handle the null case gracefully (render
   "Session failed, no details available" instead of blank banner).
3. **Multi-line error messages.** Some errors include newlines (the
   MCP SDK's "Streamable HTTP error: bad request: error: invalid
   apiVersion\n" has a trailing newline; some have multiple). Strip
   leading/trailing whitespace, collapse internal newlines to single
   spaces before truncating to 512.
4. **Should `meta-end-session` with a non-success outcome populate
   `failure_reason`?** Today an agent can end its session with a
   summary — if the summary indicates failure, should it surface the
   same way? Probably not — `meta-end-session` is intentional, not a
   crash. Keep `failure_reason` for runtime crashes only; intentional
   end-states live in the conversation.

## Resolved questions

- **Where does the banner render — agent console only, or also the MCP
  client?** Agent console only for v1. The MCP client's session listing
  is a separate surface; if MCP-facing UX needs the same, it'd consume
  the same `failure_reason` field through the existing
  `agent-applications-sessions-retrieve` MCP tool. No new platform
  work.
- **Should `state: 'cancelled'` also get a `failure_reason`?** No.
  Cancelled is a deliberate user action; failed is a crash. The two
  should stay distinguishable. If a `cancellation_reason` is wanted
  later it lands as a separate field.

## Out of scope

- **Surfacing model provider errors mid-turn** (rate limit, etc.) as
  a non-terminal failure state. Today the model error path either
  retries or marks the session failed; intermediate "transient failure
  with retry" status is a separate redesign.
- **Aggregating crash rates by agent / by failure_reason** for fleet
  observability. Plumbing the field into a Kafka stream for analytics is
  a future follow-up; this plan is about per-session visibility for the
  agent author.
- **Editing or clearing `failure_reason` from the UI.** Once a session
  is terminal it stays terminal; the failure reason is a historical
  fact, not an editable annotation.

## Rollout sequence

Two PRs, each independently shippable:

1. **PR 1 — Layer 1 (LogSink wiring + token scrubber).** ~60 LOC. No
   schema work. Lands first because it's the minimum-viable
   improvement for the "I have no idea why this failed" experience.
2. **PR 2 — Layer 2 (failure_reason field + console banner).** ~80
   LOC. Schema add + Django migration + console UI delta. Lands
   after PR 1 has soaked in real usage and we've seen which crash
   messages are common enough to optimize the banner copy for.

Between PR 1 and PR 2: every session crash has full structured log
context in the Logs tab. After PR 2: every failed session has the
reason on the header banner too, no tab-clicking required.

## Related plans

- [`runtime-mcps-auth-discovery.md`](runtime-mcps-auth-discovery.md) —
  the recent runtime-MCP work whose first user-visible bug
  (`invalid apiVersion`) motivated this plan. Tier 1 of that work
  shipped; this plan ensures the next runtime-MCP bug doesn't
  require operator access to debug.
- [`per-session-access-elevation.md`](per-session-access-elevation.md)
  — already uses the session row's structured fields for the elevation
  state machine. The `failure_reason` field follows the same pattern
  (structured data on the row, rendered by the console).
- [`approval-gated-tools.md`](approval-gated-tools.md) — gated tool
  flows currently surface their state through structured fields on
  the session row. This plan extends that "session row carries the
  user-visible state" pattern to crash reasons.
