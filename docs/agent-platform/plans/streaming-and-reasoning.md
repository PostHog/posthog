# Design — streaming deltas + unified reasoning knob

**Status:** draft. **Owner:** ben.

Two pi-ai surfaces today, treated as one design here because they touch
the same code paths in the runner and the same `Model` selection layer.

## 1. Problem

### 1.1 Streaming

`run-turn.ts` calls `pi.invoke()` and waits for the **full**
`AssistantMessage` before publishing anything to the
`SessionEventBus`. That works correctly but the UX is "spinner for 5–30s,
then the whole reply appears at once":

- The Slack adapter can't post a typing indicator that actually reflects
  partial output.
- The in-PostHog chat scene's `/listen` SSE stream goes silent during
  inference, then dumps a wall of text.
- Tool-call args don't arrive until the model finishes the whole turn
  — for repo-readonly tools this is fine, but for long-running
  reasoning chains it makes the agent feel frozen.

pi-ai's `stream(model, context, opts)` already exposes per-token
deltas. We're just not wiring them.

### 1.2 Reasoning

Three families of reasoning-capable models are in scope:

- Anthropic extended thinking (`claude-sonnet-4-5`, `claude-opus-4-7`)
- OpenAI o-series (`o4-mini`, `o5`)
- Gemini 2.5 / Gemini thinking variants

Each provider has a different knob name (`thinking_budget`,
`reasoning_effort`, `thinking_config.thinkingBudget`). pi-ai already
normalizes these behind `SimpleStreamOptions.reasoning: 'low' | 'medium'
| 'high'`, but `AgentSpec` has no place to set it. Authors who want a
reasoning agent today get whatever the provider default is.

## 2. Why these belong in one plan

Both land through the same change to `PiClient`:

- `PiClient.stream(model, context, opts)` becomes the runner's primary
  inference call.
- `opts.reasoning` is the new normalized knob, plumbed alongside
  `apiKey` / `maxTokens` / `signal`.

If we ship streaming without reasoning, we'll touch every signature
again to add reasoning a week later. If we ship reasoning without
streaming, the extended-thinking output is invisible to the SSE
consumers anyway. Sequence them together.

## 3. Spec shape

Add one optional field to `AgentSpec`:

```typescript
export const ReasoningEffortSchema = z.enum(['low', 'medium', 'high'])

export const AgentSpecSchema = z.object({
  model: ModelIdSchema,
  // ... existing fields ...
  reasoning: ReasoningEffortSchema.optional(), // NEW
})
```

Validation at freeze time:

- No constraint on `model` ↔ `reasoning` pairing. pi-ai accepts the
  knob for any provider; non-reasoning models silently ignore it.
- Default omitted (not `'low'`). Omitted means "provider default" —
  important so existing agents don't get reasoning charges they didn't
  opt into.

Janitor `validate-spec.ts` doesn't need a new check — zod parses it,
and the runner only forwards the value.

## 4. PiClient surface

Today:

```typescript
export interface PiClient {
  invoke(model: Model<string>, context: Context, opts?: InvokeOpts): Promise<AssistantMessage>
}

export interface InvokeOpts {
  maxTokens?: number
  temperature?: number
  apiKey?: string
  signal?: AbortSignal
}
```

After:

```typescript
export interface PiClient {
  invoke(model: Model<string>, context: Context, opts?: InvokeOpts): Promise<AssistantMessage>
  stream(model: Model<string>, context: Context, opts?: StreamOpts): AsyncIterable<StreamDelta>
}

export interface InvokeOpts {
  maxTokens?: number
  temperature?: number
  apiKey?: string
  signal?: AbortSignal
  reasoning?: 'low' | 'medium' | 'high' // NEW
}

export interface StreamOpts extends InvokeOpts {
  /**
   * Optional override of how often delta events are flushed to the
   * consumer. Default flushes per pi-ai chunk; set to e.g. 50 for
   * batched delivery on slow consumers.
   */
  flushIntervalMs?: number
}

export type StreamDelta =
  | { type: 'text_delta'; text: string }
  | { type: 'thinking_delta'; thinking: string; redacted?: boolean }
  | { type: 'toolcall_start'; id: string; name: string }
  | { type: 'toolcall_delta'; id: string; argsDelta: string }
  | { type: 'toolcall_end'; id: string; name: string; arguments: Record<string, unknown> }
  | { type: 'end'; assistantMessage: AssistantMessage }
```

The terminal `end` event carries the fully-materialized
`AssistantMessage` so the runner doesn't have to re-derive it from the
deltas. (pi-ai already produces this; we pass it through.)

`invoke()` stays — `FauxPiClient` and tools that don't need streaming
keep using it. In the runner we switch over.

## 5. Event-bus extensions

New `SessionEventKind` variants:

```typescript
export type SessionEventKind =
  | 'session_started'
  | 'turn_started'
  | 'assistant_text' // existing — full text block, kept for non-streaming consumers
  | 'assistant_text_delta' // NEW
  | 'assistant_thinking' // NEW (full thinking block)
  | 'assistant_thinking_delta' // NEW
  | 'tool_call' // existing — full args
  | 'tool_call_start' // NEW — id + name only, args arriving
  | 'tool_call_args_delta' // NEW — incremental JSON
  | 'tool_result'
  | 'completed'
  | 'waiting'
  | 'failed'
```

Why both `assistant_text_delta` AND `assistant_text`: SSE consumers
that don't want to assemble deltas (analytics ingestion, the activity
log, log-entries Kafka topic) keep getting one event per turn with the
full text. Live-UI consumers subscribe to the delta stream.

The activity-log integration (introduced by
[`per-session-access-elevation.md`](per-session-access-elevation.md))
writes only the full-text events — deltas are too high-cardinality.

## 6. run-turn.ts changes

The turn loop becomes:

```typescript
const stream = deps.pi.stream(deps.model, context, {
  apiKey: deps.apiKey,
  maxTokens: 4096,
  signal: deps.shutdownSignal,
  reasoning: rev.spec.reasoning, // NEW
})

let assistantMessage: AssistantMessage | null = null
for await (const delta of stream) {
  if (deps.shutdownSignal?.aborted) {
    return { state: 'suspended', reason: 'shutdown', turns }
  }
  switch (delta.type) {
    case 'text_delta':
      await emit('assistant_text_delta', { turn: turns, text: delta.text })
      break
    case 'thinking_delta':
      await emit('assistant_thinking_delta', {
        turn: turns,
        thinking: delta.thinking,
        redacted: delta.redacted ?? false,
      })
      break
    case 'toolcall_start':
      await emit('tool_call_start', { turn: turns, id: delta.id, name: delta.name })
      break
    case 'toolcall_args_delta':
      await emit('tool_call_args_delta', { turn: turns, id: delta.id, argsDelta: delta.argsDelta })
      break
    case 'toolcall_end':
      // Full tool_call event still emitted — dispatcher uses this.
      break
    case 'end':
      assistantMessage = delta.assistantMessage
      break
  }
}

if (!assistantMessage) {
  // pi-ai contract: end is always emitted unless we aborted
  return { state: 'failed', reason: 'no_assistant_message', turns }
}

// Existing post-turn path takes over: assistant_text + tool_call events,
// persistence, tool dispatch.
```

Tool dispatch still waits for `toolcall_end` (full args). That preserves
the existing dispatcher contract — we don't dispatch partial calls.

## 7. RedisSessionEventBus implications

Today the bus publishes one event per pi-ai turn. With deltas, a single
turn produces dozens-to-hundreds of events:

- Cross-host SSE fan-out still works (Redis pub/sub handles the volume).
- Storage cost on log-entries Kafka topic could balloon if we forward
  deltas. **We don't.** The KafkaLogSink subscribes only to
  `assistant_text` / `assistant_thinking` / `tool_call` / `tool_result`
  / lifecycle events — not the `*_delta` family.
- The /listen SSE consumer sees everything by default; clients that
  want a less chatty stream can pass `?kinds=assistant_text,tool_call`
  to filter on the wire (new query param, opt-in).

## 8. FauxPiClient

For tests, `FauxPiClient.stream()` returns a scripted async iterable
that yields deltas in order. The harness gets a new builder:

```typescript
streamedTurn([
  textDelta('Hello, '),
  textDelta('world!'),
  text('Hello, world!'), // existing — used as the `end` event's assistantMessage
])
```

This lets tier-2 cases assert on per-delta event emission without
needing a real provider.

## 9. Open questions

1. **Backpressure.** If the SSE consumer is slow, do we buffer deltas
   in memory or drop? Plan: bounded buffer of 1k events per session;
   beyond that we collapse adjacent `text_delta`s server-side. The
   stream still finishes; the UI just sees larger increments.
2. **Tool-call args parsing on the fly.** Today we wait for `toolcall_end`
   and JSON-parse the full args string. With incremental args, we
   could speculatively start a sandbox warm-up while args arrive. Out
   of scope for v0 — adds complexity, dispatcher contract change.
3. **Reasoning + sandboxed inference (C.1).** When a `repo-write`
   agent uses `reasoning: 'high'`, the thinking blocks may contain
   code references / file paths. The artifact channel
   (C.1 §7) should accept thinking blocks for review (so a human
   approver sees the model's reasoning). Cross-cut; mention in C.1.
4. **Per-revision reasoning override at invoke time.** Could accept
   `?reasoning=low` on chat `/run` as a runtime override for a/b
   testing. Out of scope for v0 — let authors create separate
   revisions instead.

## 10. Rollout

**v0 — PiClient surface + spec field.**

- `stream()` on `PiClient`; thin wrapper around pi-ai's stream API.
- `reasoning` on `AgentSpec` zod schema, plumbed through `InvokeOpts`.
- Backward compatible: existing `invoke()` keeps working; the runner
  defaults to `invoke()` until v1.
- Tests: `FauxPiClient.stream()` scripted iterable; `run-turn.test.ts`
  covers the spec-field forwarding via `invoke()` opts.

**v1 — runner switches to `stream()`.**

- `run-turn.ts` consumes the stream, emits delta events.
- New event kinds wired into `SessionEventBus`, `KafkaLogSink`
  excludes deltas.
- e2e case: `tier-2/streaming-turn.test.ts` asserts the delta sequence
  for a scripted faux provider.

**v2 — opt-in delta filtering on /listen.**

- `?kinds=` filter on the ingress SSE endpoint.
- Backpressure: bounded-buffer / collapse-text-deltas behavior.

## 11. Dependencies + what this enables

**Hard depends on:** nothing. Pure runner-layer change.

**Composes with:**

- [`per-session-access-elevation.md`](per-session-access-elevation.md)
  §8 activity-log integration — the deltas don't write into the
  activity log, only the full-text events do.
- [`long-running-sessions.md`](long-running-sessions.md) — streaming
  inside a `waiting → resumed` transition behaves the same; the
  stream contract is per-turn, not per-session.
- [`sandboxed-agent-inference.md`](sandboxed-agent-inference.md) §7
  artifact channel for surfacing thinking blocks to approvers.

**What this unblocks:**

- Slack typing indicators that reflect actual model progress.
- Chat-UI live token rendering (the in-PostHog scene shells a typing
  cursor through the SSE stream).
- Cost reporting per-thinking-block once
  [`per-turn-cost-capture.md`](per-turn-cost-capture.md) lands —
  reasoning tokens are a separate usage line in pi-ai.
