# Design — resumable conversations / prior-log loading from ClickHouse

**Status:** draft / open questions. **Owner:** ben. **Tracking:** TODO B8 in `services/agent-shared/TODO.md`.

## Problem

Today a session's conversation history lives in two places:

- **`agent_session.conversation` JSONB** (the queue DB) — the live, authoritative
  copy. The runner reads + writes it every turn.
- **`log_entries` table in ClickHouse** (via the `KafkaLogSink`) — an
  append-only audit log of every lifecycle event (session_started,
  turn_started, assistant_text, tool_call, tool_result, completed, waiting,
  failed). Written but never read.

When a session is `waiting` (parked on `@posthog/meta-ask-for-input`) and a
user replies hours / days later, the runner picks the row back up and continues
from `conversation` JSONB. This works.

What we _can't_ do today, and the user-visible feature we want:

1. Show a user the full audit log of an old session, even after the queue row
   has been purged.
2. Let an agent "carry context forward" across more conversations than the
   queue row can hold (the JSONB grows unbounded today — eventually we'll
   need to evict or summarize).
3. Replay a failed session for debugging.

All three want the CH `log_entries` read path. None exist yet.

## Open questions to resolve before implementing

### 1. Source of truth on resume

If both the queue row's `conversation` JSONB _and_ the CH log are populated,
which wins? Options:

- **(a) JSONB is canonical, CH is read-only.** Resume always reads JSONB.
  CH is purely for show-the-user / debug. Easiest; matches today's behavior.
- **(b) CH is canonical, JSONB is a cache.** Resume rebuilds from CH on every
  pickup. Lets us evict JSONB freely. Slow per-resume but unbounded history.
- **(c) JSONB until eviction, then CH.** A janitor evicts JSONB past N turns;
  resume falls back to CH for the prefix. Cheapest in steady state, hardest
  to reason about.

Lean toward **(a)** for v1 — solves the "show me old sessions" use case
without coupling resume to CH availability.

### 2. Schema fit

`log_entries` rows are event-shaped (`{ event, data: {…} }`); the runner
wants pi-ai-shaped `Message[]`. Mapping is lossy in both directions:

- `assistant_text` event → `{ role: 'assistant', content: [{ type: 'text', text: … }] }`
  — clean.
- `tool_call` + `tool_result` event pair → `{ role: 'assistant', content: [{ type: 'toolCall', … }] }`
  - `{ role: 'toolResult', toolName: …, content: […] }` — needs pairing by id.
- The full `AssistantMessage` (api / provider / model / usage / stopReason) is
  lost — `log_entries.data` only stores `text` / `args` / `name` / `id`.

Options:

- **Loss-tolerant rebuild.** Reconstruct a "plausible enough" `Message[]` for
  display. Resume uses JSONB instead. (Pairs with source-of-truth option a.)
- **Richer event schema.** Add `assistant_message_full` events that carry
  the entire AssistantMessage JSON. Inflates `log_entries` by ~30%; lets
  resume from CH.

Lean toward **loss-tolerant** for v1 — keep `log_entries` lean, only use it
for human-facing UI.

### 3. Compression / windowing

A long-running agent (chat with N turns) accumulates an N-turn conversation
in JSONB. Models have context windows. Today: the runner sends the whole
conversation to pi-ai every turn — works until you hit the context window.

This deserves its own design pass; not blocking the CH read path. Sketch:

- A "summarize when over threshold" step that asks the model to summarize
  the first K turns into one synthetic message, then drops those K from
  the live `conversation` JSONB (preserves them in CH for replay).
- A static "max conversation length" knob in `spec.limits` that hard-caps
  retention.

### 4. Trigger semantics

When does the read path get invoked?

- **(a) On every session list / detail view in the UI.** The user opens an
  old session → CH query → render. Bounded scope, cheap.
- **(b) On every resume.** Adds latency to every `/send`. Probably wrong.
- **(c) On explicit "replay" / "debug" actions.** Bounded scope, no
  latency cost on the hot path. Likely the right starting point.

Lean toward **(a) + (c)**: viewing-only.

## Implementation sketch (after answering the above)

1. New helper in `agent-shared/src/persistence/log_replay.ts` (or in a new
   `ch-log-reader` module that doesn't sit in agent-shared, since it needs
   a CH client). Parameterized CH query: `instance_id = session_id`,
   `team_id = team_id`, ordered by timestamp.
2. Mapper: events → display messages (loss-tolerant).
3. Janitor endpoint: `GET /sessions/:id/log` returns the mapped messages.
4. Django proxy + MCP tool: `agent-applications-revisions-sessions-log-retrieve`.

## What this unblocks

- "Show me the conversation" UI on old sessions.
- Debug / replay for failed sessions.
- Future: summarize-and-evict workflow for long conversations.

## Out of scope

- Bi-directional sync (write back to JSONB from CH). Never.
- Real-time tailing via CH. The SSE bus already covers that.
- Cross-session memory (agent remembers a user across sessions). Separate
  design — would need a new `agent_memory` table + ingestion path.
