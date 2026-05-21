# 02 — Core functionality (SSE relay + frontend stream processor)

> **Coexistence mode** ([`BACKWARD_COMPAT.md`](./BACKWARD_COMPAT.md)). LangGraph conversations stream today's wire format and consume today's `maxThreadLogic` event handlers verbatim. Sandbox conversations stream raw ACP through a `StoredLogEntry` envelope and consume a new frontend stream processor. The two paths share `maxThreadLogic`'s outer shell (thread state, request lifecycle) but split at the SSE-event-handler level.

This spec covers two surfaces:

1. The Django **SSE relay** at `/conversations/stream/` for `agent_runtime === 'sandbox'`.
2. The new frontend module that turns raw ACP into thread-shaped state.

Tool rendering off the processor's output is owned by [`03_RICH_UI.md`](./03_RICH_UI.md); context wrapping is [`01_CONTEXT.md`](./01_CONTEXT.md); the systemPrompt build is [`04_PROMPTS.md`](./04_PROMPTS.md).

---

## 1. Today: how `/conversations/stream/` works

`POST /api/environments/{teamId}/conversations/stream/` opens an SSE response carrying conversation lifecycle events: `message`, `conversation_update`, `status`, `error`. The frontend `maxThreadLogic.tsx` consumes these via an `eventsource-parser` loop. Each event name dispatches to a specific handler that folds the payload into thread state.

The frontend has been partially prepped for sandbox already — see `maxThreadLogic.tsx:67, 2130, 2145, 2155` and `Thread.tsx:237` for the existing `AssistantEventType.SANDBOX` + `parseLogEvent` + `sandbox-` message-id plumbing. The new sandbox path described below replaces and generalizes that scaffold.

The LangGraph runtime continues to use this surface unchanged for users without the `posthog-ai-sandbox` flag. The branching decision lives in the view, gated on `Conversation.agent_runtime`.

---

## Iteration plan

The rest of this document describes the **end state**. The work splits into three iterations, each a ship-able vertical behind the `posthog-ai-sandbox` flag. Section headers downstream carry `[I1]` / `[I2]` / `[I3]` tags; ambiguity is resolved by this table.

| Iteration | Goal | Sections in scope | Out of scope |
|---|---|---|---|
| **I1 — vertical slice ("hello world")** | One user message → streamed response, end-to-end through the sandbox path. Internal devs only. | § 2, § 3, § 4.1 (acp / status / error events only), § 4.2 (single-Run bootstrap), § 4.5, § 5.1, § 6 (skeleton: `agent_message_chunk` / `agent_message` dispatch + placeholder tool cards), § 7.1, § 7.2 (acp handler), § 7.3, partial § 11 | Multi-turn within a Run, resume across Runs, history retrieval for existing conversations, approvals, slash command gating, reconnect/backoff, pre-warming. Tool rendering = text-only placeholder; full registry runs in parallel via `03_RICH_UI.md` after I1 unblocks the wire format. |
| **I2 — sustained conversations** | Multi-turn, resume after terminal, reopening old conversations, reconnect resilience. | § 4.2 (multi-Run chain upgrade), § 4.3, § 4.4, § 4.6, § 4.7, § 5.2, § 5.3, § 5.4, § 6 (full ACP dispatch + boundary events), § 7.2 (status/error handlers), § 9, § 10 | Approvals, slash command gating, race-handling for terminal-then-resume, pre-warming. |
| **I3 — production-ready** | Approvals, slash command UX, race-hardening, pre-warming integration. | § 5.5, § 6 (`permission_request` ingest), § 7.2 (full dispatch arms), § 8, § 12 (race handling: cloud-agent dup-create idempotency + relay-side `SELECT FOR UPDATE` if needed), integration with `05_SANDBOX.md` § 8 pre-warming | — |

Each iteration ships independently behind the same `posthog-ai-sandbox` flag. I1 unlocks internal smoke testing. I2 unlocks sustained dogfooding. I3 unlocks broader internal release.

**Parallel streams** (don't serialize behind this spec's iterations):

- **`03_RICH_UI.md` registry + fallback card** — can ship during I1; per-tool adapters land per-tool behind `posthog-ai-sandbox-tool-{slug}` after I1 unblocks the wire format.
- **`04_PROMPTS.md` MCP servers** — independent; `posthog-data` can land in parallel with I1.
- **`05_SANDBOX.md` § 8 pre-warming** — slot into I3; endpoint scaffolding can prototype earlier.

---

## 2. Model changes [I1]

### 2.1 `Conversation.agent_runtime`

```python
class Conversation(...):
    class AgentRuntime(models.TextChoices):
        LANGGRAPH = "langgraph"
        SANDBOX = "sandbox"

    agent_runtime = models.CharField(
        max_length=16,
        choices=AgentRuntime.choices,
        default=AgentRuntime.LANGGRAPH,
        db_index=True,
    )
```

Stamped at conversation create time from the `posthog-ai-sandbox` feature flag. **Never re-read on an existing row** — a conversation lives its whole life on the runtime it was created with. Existing rows default to `langgraph`; no backfill needed.

Following the [`django-migrations`](https://docs.posthog.com/handbook/engineering/django-migrations) skill: non-nullable string with a default is a safe Postgres-side `ADD COLUMN` (single transaction, no rewrite for the existing rows because the default lives in the catalog metadata in PG 11+).

### 2.2 Task / Run references on `Conversation`

The conversation row gains a single foreign key into the cloud-agent Task model (`products/tasks/backend/models.py::Task`). The Task lives in the same Postgres database as `Conversation`, so a real FK is correct — referential integrity, cascade control, and ORM ergonomics all matter.

```python
sandbox_task = models.ForeignKey(
    "tasks.Task",
    null=True,
    blank=True,
    on_delete=models.SET_NULL,
    related_name="+",          # no reverse accessor — would be confusing
    db_index=True,
)

# Current Run is derived, not stored. The Task's reverse relation gives every
# Run; the latest by created_at is the active one.
@property
def current_sandbox_run(self) -> Optional["TaskRun"]:
    if not self.sandbox_task_id:
        return None
    return self.sandbox_task.runs.order_by("-created_at").first()
```

`on_delete=SET_NULL` is deliberate. Conversations are user-facing artifacts; if the backing Task row is ever cleaned up (admin action, retention policy, future cleanup tooling), the conversation should survive with a nulled pointer rather than vanish. Conversations with `sandbox_task = NULL` on a non-LangGraph row are surfaced as "history only" — readable from the persisted ACP log but unable to accept new turns. `CASCADE` would silently delete user-visible history.

**Why derived `current_sandbox_run`, not a stored FK.** A conversation can accumulate many Runs over its life (one per terminal+resume cycle — see § 5.3 and `05_SANDBOX.md` § 9). All Runs share the same `Task`; the latest by `created_at` is by definition the one that next user messages target. Storing a second FK to "the current Run" would denormalise this fact and create a consistency hazard — two concurrent tabs both creating successor Runs after a terminal predecessor would race the `Conversation.sandbox_run` update; whichever transaction commits second wins, but in the wrong direction. Derivation closes that hole: `ORDER BY created_at DESC LIMIT 1` always picks the most recent Run deterministically, regardless of update ordering. The query cost is one indexed lookup — negligible.

The on-disk consequence is that we delete (or never write) the `sandbox_run_id` UUID column, and we **do not reuse** the existing `sandbox_task_id` UUID column either. Both UUID columns from the partial `executor.py` Redis flow are deprecated and dropped outright; the new `sandbox_task` FK is a fresh column.

Migration plan (single migration, no in-place rename):

1. Add the new `sandbox_task` FK column (nullable, default NULL).
2. Drop the legacy `sandbox_task_id` UUID column.
3. Drop the legacy `sandbox_run_id` UUID column.

Both legacy columns are dropped without backfill — the Redis-relay flow they were attached to never shipped beyond internal experimentation, so there's no production data to preserve. Any caller that still references them gets a `column does not exist` error at PR time, surfaced by the typechecker and the integration tests. Cleaner than a `SeparateDatabaseAndState` rename — no risk of two columns transiently coexisting, no `db_column` indirection, no follow-up migration to clean up.

The [`django-migrations`](https://docs.posthog.com/handbook/engineering/django-migrations) skill governs the migration shape; dropping nullable columns is safe in a single transaction on Postgres.

Semantics for sandbox-runtime conversations:

| Field          | When set                                            | When updated                                                          |
| -------------- | --------------------------------------------------- | --------------------------------------------------------------------- |
| `sandbox_task` | First message of the conversation creates the Task. | Never. One Task per conversation for its whole life.                  |
| `current_sandbox_run` (property) | Returns `None` until the first Run is created. Resolves to the latest Run by `created_at` afterwards. | Auto-updates whenever a new Run is inserted on the Task. |

The Task carries the agent-server lifecycle; Runs carry per-session bookkeeping. The conversation row only needs to know the Task — the current Run falls out of the data.

Per CLAUDE.md, both `Task` and `TaskRun` already carry `team_id` for tenant isolation; the FK doesn't change that — the relay's permission check still happens against `request.user`'s team membership before any cross-table query.

### 2.3 Feature-flag resolution at create-time

In the conversation-create view (existing `/conversations/` POST or implicit on the first `/conversations/stream/` call):

```python
if posthoganalytics.feature_enabled("posthog-ai-sandbox", user.distinct_id):
    conversation.agent_runtime = Conversation.AgentRuntime.SANDBOX
```

Once written, the flag is not re-evaluated. A user who loses the flag mid-conversation continues to see the existing chat on the sandbox runtime.

---

## 3. The view — branching on `agent_runtime` [I1]

```python
@api_view(["POST"])
def conversation_stream(request, conversation_id):
    conversation = Conversation.objects.get(...)

    if conversation.agent_runtime == Conversation.AgentRuntime.SANDBOX:
        return sandbox_stream_response(request, conversation)

    # Existing LangGraph code path — UNCHANGED.
    return langgraph_stream_response(request, conversation)
```

One `if` branch. The LangGraph branch is preserved byte-for-byte (the existing code path runs first). Everything new lives behind the early-return.

---

## 4. The SSE relay (sandbox branch)

A thin streaming response that:

1. Reads `attached_context` + `content` + `trace_id` from the request body.
2. Wraps the user content via `ee/hogai/sandbox/context_wrapper.py::wrap_user_message(content, attached_context)` ([`01_CONTEXT.md`](./01_CONTEXT.md) § 4.3).
3. On the **first** user message in the conversation:
   - Builds the system prompt via `ee/hogai/sandbox/system_prompt.py::build_posthog_ai_system_prompt(...)` ([`04_PROMPTS.md`](./04_PROMPTS.md) § 6).
   - `POST /api/projects/{tid}/tasks/` to create the Task (no repository, no GitHub integration — per [`04_PROMPTS.md`](./04_PROMPTS.md) § 2.3).
   - `POST /api/projects/{tid}/tasks/{taskId}/run/` to start the Run, passing the system prompt, the wrapped user content as `pending_user_message`, and `state.attached_context` as a structured record.
   - Persists `conversation.sandbox_task`. `current_sandbox_run` automatically resolves to the just-created Run via the Task's reverse relation.
4. On subsequent messages in the same conversation:
   - **In-progress Run** → `POST /api/projects/{tid}/tasks/{taskId}/runs/{runId}/command/` with method `user_message`, `params.content = wrapped`, `params._meta.attached_context = [...]`.
   - **Terminal Run** → create a new Run via `POST /tasks/{taskId}/run/` with `state.resume_from_run_id = previous_run_id`. No conversation-row update needed — the new Run's `created_at` makes it `current_sandbox_run` automatically.
5. Opens the upstream SSE stream at `GET /api/projects/{tid}/tasks/{taskId}/runs/{runId}/stream/`.
6. Relays raw ACP frames downstream to the client, wrapped in a `StoredLogEntry` envelope (the existing upstream wire shape — see cloud spec § 5.3).

### 4.1 Wire format — passthrough, mirroring PostHog Code precedent [I1]

The relay matches PostHog Code's SSE wire shape exactly (`Twig/apps/code/src/main/services/cloud-task/service.ts:693`). The bulk of traffic is the **default SSE event** (`event: message` per SSE spec), with a JSON `data` envelope discriminated by `data.type`. Only `error` and `keepalive` are named events.

```http
id: <upstream Last-Event-ID, if any>
data: { "type": "notification", "timestamp": "...", "notification": { "method": "session/update", "params": { ... } } }

id: <…>
data: { "type": "task_run_state", "status": "completed", "errorMessage": null }

id: <…>
data: { "type": "permission_request", "requestId": "...", "toolCall": { ... }, "options": [ ... ] }

event: keepalive
data: { "type": "keepalive" }

event: error
data: { "errorTitle": "...", "errorMessage": "...", "retryable": true }
```

`data.type` discriminates inside the default event:

| `data.type`          | Source                                                                     | Payload shape                                                       | Frontend handler                                                                     |
| -------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `notification`       | Every ACP notification from the upstream stream                            | `StoredLogEntry` (cloud spec § 2.8; `Twig/apps/code/src/shared/types/session-events.ts`) | The new `sandboxStreamLogic` (§ 6)                                                   |
| `permission_request` | Upstream emits a `permission_request` frame                                | `{ requestId, toolCall: {...}, options: [...] }`                    | The new `sandboxStreamLogic` _and_ the existing approval surface in `maxThreadLogic` |
| `task_run_state`     | Terminal status change (status ∈ {completed, failed, cancelled})           | `{ status, stage?, output?, errorMessage? }`                        | Existing `maxThreadLogic` Idle/Error transition                                      |
| `keepalive`          | Liveness ping from upstream (also filterable as `event: keepalive`)        | `{ type: 'keepalive' }`                                             | Ignored                                                                              |

Named events:

| `event:` name | Payload shape                                  | Frontend handler                                  |
| ------------- | ---------------------------------------------- | ------------------------------------------------- |
| `error`       | `{ errorTitle, errorMessage, retryable }`      | Existing `maxThreadLogic` error handler           |
| `keepalive`   | `{ type: 'keepalive' }`                        | Ignored                                           |

No frame-level translation of `data.type === 'notification'` payloads — the agent's ACP notifications flow through verbatim. The frontend stream processor (§ 6) dispatches on `notification.method` + `notification.params.update.sessionUpdate` exactly as PostHog Code's renderer does.

**`trace_id` propagation.** The agent-server does **not** thread inbound `_meta.trace_id` from `POST /command/` calls onto outbound `user_message_chunk` notifications (verified in `Twig/packages/agent/src/adapters/claude/claude-agent.ts:1593-1605` — `broadcastUserMessage` builds the notification without `_meta`; the inbound `_meta` on `POST /command/ user_message` is ignored inside `agent-server.ts:602`). The relay maintains a `{ runId → traceId }` map server-side and stamps `traceId` into each forwarded envelope's `data.traceId` at emit time. No agent-server fork required.

Filtered/dropped at the relay (not forwarded):

- `keepalive` frames: optionally re-emit as `event: keepalive` (matches PostHog Code), or drop entirely if the downstream SSE library handles liveness.
- _Nothing else._ Even noisy `_posthog/console`, `_posthog/progress`, `_posthog/sdk_session` frames are forwarded — the renderer filters at display time (and a debug toggle exposes them per Twig § 17 precedent).

### 4.2 Bootstrap (multi-Run chain + REST + SSE merge with content-dedup) [I1 single-Run; I2 chain walk]

A conversation can have many Runs over its life (one per terminal+resume cycle — § 5.3). Each Run has its own NDJSON log in S3; together they form the full conversation history. The bootstrap assembles all of them into one chronological view for the frontend.

**Fresh-conversation fast path.** When the relay's path through § 4 just created the Task + first Run for this request (no prior Runs exist), the bootstrap below has nothing to assemble — skip the multi-Run walk entirely and proceed straight to SSE. One flag in the relay (`just_created_run: bool`) gates this; saves one REST round-trip on every first-message-of-a-conversation request.

On open of a conversation with a non-null `sandbox_task` **and** prior Runs (i.e. not the fresh-conversation fast path):

1. **Enumerate the Task's Runs in chronological order.** One query:
   ```python
   runs = list(
       TaskRun.objects
       .filter(task_id=conversation.sandbox_task_id)
       .order_by("created_at")
       .values("id", "status", "created_at")
   )
   ```
   The last entry in this ordered list is `conversation.current_sandbox_run` (the derived property from § 2.2). No invariant to check — the list *defines* the current Run.

2. **For each terminal predecessor Run** (all entries except the last when the last is non-terminal): paginate `GET /api/projects/{tid}/tasks/{taskId}/runs/{runId}/session_logs/?limit=5000` until `X-Has-More: false`. These logs are guaranteed complete (no live SSE could be adding more — the Run is terminal). Collect into the chronological `StoredLogEntry[]` buffer.

3. **For the current Run** (the last entry):
   - `GET /api/projects/{tid}/tasks/{taskId}/runs/{currentRunId}/` to capture status/output/error.
   - **If terminal**: paginate its `session_logs/`, append to the buffer, emit one `event: snapshot` carrying `{ entries: StoredLogEntry[], terminal_status, error_message? }`. Do not open SSE.
   - **If non-terminal**: open SSE with `?start=latest`. Concurrently paginate the current Run's `session_logs/`. Buffer live SSE entries until history is loaded. Emit one `event: snapshot` with the full concatenated chain. Then drain the SSE buffer, content-deduping by serialized JSON of each `StoredLogEntry` against the current Run's portion of history (cloud spec § 9.4 — Redis-stream IDs aren't comparable to S3-log IDs).

The agent-server in the current Run has already done its own `resumeFromLog` walk to rehydrate the model's context across the chain. That happens sandbox-side and is invisible to us; the frontend rendering is the only consumer that needs the relay to assemble the chronological view.

**Long-conversation perf note.** A conversation that's accumulated dozens of Runs needs dozens of paginated REST round-trips. Acceptable for the common case (1–3 Runs); becomes slow past ~10. Mitigations if it matters: parallelize the fetches with `asyncio.gather`, or cache a concatenated `StoredLogEntry[]` server-side keyed on the Task ID, invalidated when a new Run goes terminal. Defer until measured.

Ports the single-Run portion of `Twig/apps/code/src/main/services/cloud-task/service.ts:440-556` and adds the chain walk on top. Constants:

```python
MAX_SSE_RECONNECT_ATTEMPTS = 5
SSE_RECONNECT_BASE_DELAY_MS = 2_000
SSE_RECONNECT_MAX_DELAY_MS  = 30_000
SESSION_LOG_PAGE_LIMIT      = 5_000
```

### 4.3 Reconnect / backoff [I2]

When the upstream SSE drops:

1. Refetch the Run via REST.
2. If terminal: emit a final `event: status` and close.
3. If non-terminal: capped exponential backoff up to 5 attempts (2s / 4s / 8s / 16s / 30s), then surface a retryable `event: error`.

If the downstream client (browser) disconnects, the relay closes the upstream connection too (no orphan upstream streams). The conversation's current Run continues to execute in the sandbox regardless — the next client reconnect re-bootstraps via § 4.2.

### 4.4 Error class mapping [I2]

Upstream HTTP status from `/runs/{rid}/` or `/stream/` → conversation-stream error envelope (cloud spec § 5.6):

| Upstream | `event: error` payload                                                   | Client response                     |
| -------- | ------------------------------------------------------------------------ | ----------------------------------- |
| 401      | `{ errorTitle: 'Cloud authentication expired', retryable: true }`        | Show retry; surface re-auth         |
| 403      | `{ errorTitle: 'Cloud access denied', retryable: true }`                 | Show retry                          |
| 404      | `{ errorTitle: 'Conversation backing run not found', retryable: false }` | Surface "create a new conversation" |
| 406      | `{ errorTitle: 'Cloud stream unavailable', retryable: true }`            | Show retry                          |
| other    | `{ errorTitle: 'Cloud stream failed', retryable: true }`                 | Auto-retry per § 4.3                |

### 4.5 Module layout [I1 scaffold]

```
posthog/ee/hogai/sandbox/
    __init__.py
    types.py                ← existing
    mapping.py              ← existing
    executor.py             ← existing (Redis relay — § 12 action item: grep callers before I1 PR 5; repurpose if unused, leave otherwise)
    context_wrapper.py      ← new (01_CONTEXT § 4)
    system_prompt.py        ← new (04_PROMPTS § 6)
    sse_relay.py            ← new (this spec)
    posthog_api.py          ← new (typed HTTP client for /api/projects/{tid}/tasks/*)
    bootstrap.py            ← new (REST + SSE merge + dedup)
```

`sse_relay.py` is the entry point called from the view. It owns:

- The streaming Django response.
- The upstream SSE client (using `httpx`'s async streaming or `requests` + `iter_lines()`).
- Bootstrap orchestration.
- Reconnect/backoff loop.
- Convenience event emission.

It is **stateless across requests**. One `UpstreamSseRelay` instance per outbound HTTP response.

### 4.6 Non-streaming history retrieval [I2]

Bootstrap (§ 4.2) walks the multi-Run chain and emits a snapshot on the SSE stream. That's the right shape for "open the conversation and start receiving live updates". Two scenarios want history *without* opening a stream:

1. **Reopening a terminal conversation purely to read it.** User clicks an old conversation; all Runs are terminal; they want to see what happened, not continue. Opening SSE just to receive a snapshot + immediate close is wasteful and forces a persistent connection for a static read.
2. **History preview in `ConversationHistory.tsx`.** The conversation list shows a snippet of the most recent assistant message per row. Opening SSE per row is untenable.

Dedicated endpoint:

```http
GET /api/environments/{tid}/conversations/{conversationId}/log/
Authorization: Bearer <token>
?after=<iso-timestamp>     # optional, cursor for pagination
?limit=<n>                 # optional, default 5000, cap 5000
?order=asc|desc            # optional, default asc (chronological); desc useful for "last N entries" previews
```

Response:

```json
{
  "entries": [
    { "type": "notification", "timestamp": "...", "notification": { "method": "session/update", "params": { ... } } },
    ...
  ],
  "has_more": false,
  "current_run_status": "completed" | "failed" | "cancelled" | "in_progress" | "queued" | null
}
```

Backend implementation reuses the multi-Run walk from § 4.2 — extract it into a shared helper called by both the SSE relay's bootstrap and this REST endpoint. One assembled chronological `StoredLogEntry[]` from across all Runs on `conversation.sandbox_task`. Frontend feeds those entries straight into `sandboxStreamLogic.actions.ingestAcpFrame` — same reducer code path as live events.

**Runtime guard.** When `conversation.agent_runtime === 'langgraph'`, the endpoint returns `400 Bad Request` (or `404 Not Found`, decided at implementation) with `{ "detail": "log endpoint is sandbox-runtime only; use GET /conversations/{id}/ for langgraph messages" }`. LangGraph conversations don't have ACP logs to read.

**Permission**. Same auth check as the existing conversation endpoints — team membership on the conversation's team. No new IDOR surface.

### 4.7 Detail endpoint `messages` field — runtime-dependent [I2]

`GET /api/environments/{tid}/conversations/{conversationId}/` (existing endpoint, no path change).

| Runtime | `messages` field |
|---|---|
| `langgraph` | Populated from the Django-side `ConversationMessage` table (today's behavior — unchanged). |
| `sandbox` | **Empty array** (or absent). Sandbox conversations don't persist messages Django-side; history lives in S3 ACP logs and is fetched via § 4.6 or assembled via stream-bootstrap § 4.2. |

This split is intentional. Mirroring sandbox messages Django-side was considered (see `05_SANDBOX.md` open question #11) and rejected for the migration: it would double storage, and a `messages` field that's authoritative for one runtime but stale for the other is a worse contract than one that's empty for the runtime that owns its messages elsewhere. The detail endpoint stays fast — it doesn't paginate S3 — and metadata-only payloads remain cheap.

Frontend `maxLogic` loads history accordingly:

```ts
const detail = await api.conversations.detail(conversationId)

if (detail.agent_runtime === 'langgraph') {
    // existing path — messages came back populated in the detail response
    setThread(detail.messages)
} else {
    // sandbox — separate REST call to assemble from S3 ACP logs
    const { entries, current_run_status } = await api.conversations.log(conversationId)
    entries.forEach((entry) => sandboxStreamLogic.actions.ingestAcpFrame(entry))
    setCurrentRunStatus(current_run_status)
    // If still in_progress / queued, open SSE for live updates;
    // if terminal, this is a read-only view.
    if (!isTerminal(current_run_status)) {
        openConversationStream(conversationId)
    }
}
```

For sandbox conversations that are still in-flight, the frontend does *two* requests on open — `GET /log/` for the history, then `POST /stream/` to attach to live updates. The stream's bootstrap snapshot would duplicate what `/log/` returned, so the stream consumer must dedup (already required by § 4.2's content-dedup logic; serialized JSON match dedups against history entries we already ingested).

Alternative: skip the bootstrap snapshot when the client signals "I already have history" (e.g., a `?skip_snapshot=true` query param on the stream open). Defer until measured — content-dedup is cheap and the snapshot is small for a fresh-after-history-load scenario.

---

## 5. Lifecycle — message routing

### 5.1 First message in a conversation [I1]

```
client                  Django (sandbox_stream_response)         cloud-agent REST
  │                              │                                      │
  ├── POST /stream/ ────────────▶│                                      │
  │   { content, attached_       │                                      │
  │     context, trace_id }      │                                      │
  │                              │                                      │
  │                              ├── wrap_user_message(...)             │
  │                              │                                      │
  │                              ├── POST /tasks/ ─────────────────────▶│
  │                              ◀── { task_id } ──────────────────────┤
  │                              │                                      │
  │                              ├── POST /tasks/{id}/run/ ────────────▶│
  │                              │   { mode: 'interactive',             │
  │                              │     pending_user_message: wrapped,   │
  │                              │     state: { attached_context, ... } │
  │                              │     system_prompt }                  │
  │                              ◀── { run_id, status: 'queued' } ─────┤
  │                              │                                      │
  │                              ├── UPDATE conversation                │
  │                              │   sandbox_task                       │
  │                              │                                      │
  │                              ├── GET /runs/{id}/stream/ ───────────▶│
  ◀── event: status ─────────────┤  ◀── ACP frames ───────────────────┤
  ◀── event: acp ────────────────┤                                      │
  ◀── event: acp ────────────────┤                                      │
  ...
```

### 5.2 Follow-up message (in-progress Run) [I2]

```
  ├── POST /stream/ ────────────▶│                                      │
  │   { content, attached_       │                                      │
  │     context, trace_id }      │                                      │
  │                              │                                      │
  │                              ├── POST /runs/{id}/command/ ─────────▶│
  │                              │   {"jsonrpc": "2.0",                 │
  │                              │    "method": "user_message",         │
  │                              │    "params": {                       │
  │                              │      "content": wrapped,             │
  │                              │      "_meta": { attached_context }   │
  │                              │    }}                                │
  │                              ◀── { result: { ... } } ──────────────┤
  │                              │                                      │
  │                              │   (continues relaying same SSE)      │
  ◀── event: acp ────────────────┤  ◀── ACP frames ───────────────────┤
  ...
```

### 5.3 Follow-up message (terminal Run → new Run) [I2]

```
  ├── POST /stream/ ────────────▶│                                      │
  │   { content, ... }           │                                      │
  │                              │                                      │
  │                              │   current_sandbox_run is terminal    │
  │                              │                                      │
  │                              ├── POST /tasks/{id}/run/ ────────────▶│
  │                              │   { state: {                          │
  │                              │      resume_from_run_id: prev,        │
  │                              │      attached_context, ...           │
  │                              │     },                                │
  │                              │     pending_user_message: wrapped }   │
  │                              ◀── { run_id: new, status: 'queued' } ─┤
  │                              │                                      │
  │                              ├── UPDATE conversation                │
  │                              │   (new Run created; current resolves │
  │                              │    automatically via Task.runs)      │
  │                              │                                      │
  │                              ├── GET /runs/{new}/stream/ ──────────▶│
  ...
```

### 5.4 Cancel [I2]

`POST /conversations/{id}/cancel/` (existing endpoint) → relay dispatches `POST /runs/{rid}/command/` with method `cancel`.

### 5.5 Permission response (approval) [I3]

Today's `DangerousOperationApprovalCard` posts back via an existing conversation endpoint. The sandbox branch routes that to `POST /runs/{rid}/command/` with method `permission_response` and the option payload:

```json
{ "requestId": "...", "optionId": "allow_once" | "reject" | "reject_with_feedback" | "...", "customInput": "..." }
```

Option-kind mapping is owned by [`03_RICH_UI.md`](./03_RICH_UI.md) § 5.

---

## 6. The frontend stream processor — `sandboxStreamLogic.ts` [I1 skeleton; I2 + I3 expand dispatch]

A new Kea logic that consumes the raw ACP stream and produces thread-shaped state. **Separate from `maxThreadLogic`** so the rendering layer can evolve without re-touching ACP parsing.

### 6.1 Responsibilities

1. Subscribe to `event: acp` SSE frames received by `maxThreadLogic`'s event loop.
2. Maintain a `Map<toolCallId, ToolInvocation>` reducer that merges `tool_call` (creation) + N × `tool_call_update` (status/content/progress updates) into one record.
3. Maintain an ordered append-only list of "thread items" the renderer consumes: text chunks, tool-invocation records, permission requests, mode changes, run-lifecycle markers.
4. Emit derived selectors (`thinkingMessage`, `currentRunStarted`, `lastTurnComplete`) the existing `maxThreadLogic` can read.

It does **not**:

- Own the SSE connection (that's `maxThreadLogic`).
- Render anything (that's `Thread.tsx` + [`03_RICH_UI.md`](./03_RICH_UI.md)).
- Talk to the backend (that's `maxThreadLogic`).

### 6.2 Shape

```ts
interface ToolInvocation {
  toolCallId: string
  serverName: string // e.g. 'posthog-data'
  toolName: string // e.g. 'create_insight'
  qualifiedName: string // `${serverName}.${toolName}` — registry key for 03_RICH_UI
  input: Record<string, unknown>
  output?: unknown
  progress?: unknown
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
  title?: string
  kind?: string // ACP toolCall.kind ('switch_mode' for plan approvals, etc.)
  locations?: { path: string; line?: number }[]
  contentBlocks: unknown[] // accumulated ACP `content[]` from updates
}

interface SandboxStreamLogicValues {
  toolInvocations: Map<string, ToolInvocation>
  threadItems: ThreadItem[] // ordered renderable items
  assistantMessageBuffer: { id: string; text: string; complete: boolean }[]
  pendingPermissionRequest?: PermissionRequestRecord
  currentMode?: string // from current_mode_update
  currentProgress?: string // from _posthog/progress
  runStarted: boolean
  turnComplete: boolean
}

interface SandboxStreamLogicActions {
  ingestAcpFrame: (entry: StoredLogEntry) => void
  ingestPermissionRequest: (record: PermissionRequestRecord) => void
  reset: () => void // called when conversation changes
}
```

### 6.3 ACP dispatch — internal table

The `ingestAcpFrame` listener walks the `StoredLogEntry` and dispatches on `notification.method`:

| `method`                                                                | `params.update.sessionUpdate` | Effect                                                                                               |
| ----------------------------------------------------------------------- | ----------------------------- | ---------------------------------------------------------------------------------------------------- |
| `session/update`                                                        | `agent_message_chunk`         | Append delta to current `assistantMessageBuffer[?].text`                                             |
| `session/update`                                                        | `agent_message`               | Finalize the current buffer entry; mark `complete: true`                                             |
| `session/update`                                                        | `tool_call`                   | Create a `ToolInvocation` record keyed on `toolCallId`. Emit `ThreadItem` for it.                    |
| `session/update`                                                        | `tool_call_update`            | Mutate existing `ToolInvocation`: merge `content[]`, update `status`/`progress`/`title`/`locations`. |
| `session/update`                                                        | `current_mode_update`         | Set `currentMode`                                                                                    |
| `_posthog/run_started`                                                  | —                             | Set `runStarted = true`                                                                              |
| `_posthog/turn_complete`                                                | —                             | Set `turnComplete = true`; emit a thread-item separator                                              |
| `_posthog/progress`                                                     | —                             | Set `currentProgress` (drives `thinkingMessages.ts`)                                                 |
| `_posthog/usage_update`                                                 | —                             | Optional: capture token counts for telemetry                                                         |
| `_posthog/console` / `_posthog/sdk_session` / `_posthog/git_checkpoint` | —                             | Ignore (renderer-side debug toggle could surface them later)                                         |
| `_posthog/error`                                                        | —                             | Push to thread items as an inline error                                                              |
| any other `_posthog/*`                                                  | —                             | Ignore                                                                                               |

This dispatch is a pure function over the previous state — easily unit-testable from `StoredLogEntry` fixtures.

### 6.4 Coalescing — pre-done sandbox-side

`agent_message_chunk` events are already coalesced into `agent_message` server-side by `SessionLogWriter` (`Twig/packages/agent/src/session-log-writer.ts:112-160`). The frontend processor still buffers chunks for low-latency token streaming, but the _final_ `agent_message` event resolves the buffer to the coalesced text — no double-buffering pitfalls.

### 6.5 Where it lives

```
frontend/src/scenes/max/
    sandboxStreamLogic.ts            ← new
    sandboxStreamLogicType.ts        ← generated
    sandboxStreamLogic.test.ts       ← new (ACP-frame fixture replay tests)
    types/
        sandboxStreamTypes.ts        ← new (ToolInvocation, ThreadItem, PermissionRequestRecord)
```

Mounted lazily by `maxThreadLogic` when `conversation.agent_runtime === 'sandbox'`. Unmounted on conversation change. State is per-conversation (keyed on `conversation.id`).

### 6.6 Test surface

Snapshot fixtures from real ACP traces, fed through `ingestAcpFrame` in order, assert against the resulting `threadItems` shape. Each new MCP tool gets a fixture before the renderer adapter (per [`03_RICH_UI.md`](./03_RICH_UI.md) § 3.3) is wired up.

---

## 7. `maxThreadLogic.tsx` — additive changes [I1 request body + `case 'message'` notification arm; I2 `task_run_state` + `error` arms; I3 `permission_request` arm]

The existing logic gains a runtime branch in three places. **No existing handler is modified**; the changes are alternative branches taken only when `conversation.agent_runtime === 'sandbox'`.

### 7.1 Request body builder

```ts
// before submitting a message
if (conversation.agent_runtime === 'sandbox') {
  return {
    content,
    trace_id,
    attached_context: posthogAiContextLogic.values.attachments,
  }
}

// LangGraph path — UNCHANGED
return {
  content,
  trace_id,
  ui_context: maxContextLogic.values.compiledContext,
  billing_context: maxBillingContextLogic.values.billingContext,
  contextual_tools: maxGlobalLogic.values.tools,
}
```

### 7.2 SSE event handlers

The existing `eventsource-parser` loop routes events by name. The sandbox path matches PostHog Code's pattern: the bulk of traffic arrives on the **default** `event: message` and is discriminated by `data.type`; only `error` and `keepalive` are named events.

Add one default-event dispatch arm (for sandbox runs) plus an `error` arm:

```ts
case 'message':
    // sandbox runtime: dispatch on the JSON envelope's discriminator
    if (conversation.agent_runtime === 'sandbox') {
        const envelope = JSON.parse(data) as SandboxSseEnvelope
        switch (envelope.type) {
            case 'notification':
                sandboxStreamLogic.actions.ingestAcpFrame(envelope)
                break
            case 'permission_request':
                sandboxStreamLogic.actions.ingestPermissionRequest(envelope)
                // existing approval surface in maxThreadLogic also reads pendingPermissionRequest
                break
            case 'task_run_state':
                handleSandboxTerminalStatus(envelope)
                break
            case 'keepalive':
                // ignored
                break
        }
        break
    }
    // existing LangGraph 'message' handler — UNCHANGED
    handleLangGraphMessage(JSON.parse(data))
    break

case 'error':
    if (conversation.agent_runtime === 'sandbox') {
        handleSandboxStreamError(JSON.parse(data))
    } else {
        // existing LangGraph error handler — UNCHANGED
    }
    break

case 'keepalive':
    // ignored on both runtimes
    break
```

The existing `case 'conversation_update'` and `case 'sandbox'` (from the prior partial sandbox plumbing) keep firing for the LangGraph runtime and the legacy sandbox-debug surface respectively.

### 7.3 Thread state reads

The existing `threadGrouped` selector merges messages by `trace_id`. For sandbox conversations, the renderer (`Thread.tsx`) reads `sandboxStreamLogic.values.threadItems` instead — [`03_RICH_UI.md`](./03_RICH_UI.md) § 2 owns the dispatch.

---

## 8. Slash commands under sandbox runtime [I3]

| Command     | Sandbox runtime disposition                                | Notes                                                    |
| ----------- | ---------------------------------------------------------- | -------------------------------------------------------- |
| `/init`     | **No-op** with a "Not yet supported in sandbox AI" tooltip | Core memory dropped; see [`TODO.md`](./TODO.md) backfill |
| `/remember` | **No-op** with same tooltip                                | Same                                                     |
| `/usage`    | **Unchanged**                                              | Surfaces usage UI; independent of runtime                |
| `/feedback` | **Unchanged**                                              | Opens existing `FeedbackPrompt.tsx`                      |
| `/ticket`   | **Unchanged**                                              | Opens existing `TicketPrompt.tsx`                        |

Routing decision lives in `slash-commands.tsx`. Today's command-dispatch reducer gets a runtime-aware filter that hides or disables `/init` and `/remember` from the autocomplete for sandbox conversations. Existing LangGraph behavior preserved.

---

## 9. Multi-tab / shutdown [I2]

Two tabs open the same conversation. Each hits `/conversations/stream/` independently. The relay does **not** reference-count — each connection is its own upstream subscription. The cloud-agent SSE handles multiple subscribers natively (cloud spec § 5).

Client disconnect (browser close, navigation away): Django streaming response closes; relay aborts its upstream stream. The sandbox Run continues running independently. On reconnect, bootstrap (§ 4.2) catches up via `session_logs/` + new SSE.

---

## 10. Telemetry continuity [I2]

Existing analytics events (`PROMPT_SENT`, `TASK_RUN_CANCELLED`, `PERMISSION_RESPONDED`, etc.) fire from the same code paths as today. The sandbox path adds an `execution_type: 'sandbox'` property to each event — a new property on existing events, not a new event type. All dashboards that filter on event name keep working.

`trace_id` is generated server-side at message create, same as today. Inbound `_meta` on `POST /command/` calls is **not** propagated through to the agent-server's outbound notifications (verified in `Twig/packages/agent/src/adapters/claude/claude-agent.ts:1593-1605` — `broadcastUserMessage` builds `user_message_chunk` without `_meta`). The relay therefore maintains a `{ runId → traceId }` map server-side: when the relay forwards a user message to the agent-server, it records the trace_id; when SSE frames come back, the relay stamps `traceId` into each forwarded envelope's `data.traceId`. No agent-server fork required. The map is in-memory in the relay instance (one `sse_relay.py` instance per HTTP response — § 4.5) and dies with the request, so there's no leak.

---

## 11. Migration checklist

Each PR ships behind `posthog-ai-sandbox` for internal users. Grouped by iteration per the table in the **Iteration plan** section.

### Iteration 1 — vertical slice

1. **Conversation model migration.** Add `agent_runtime` column with default `'langgraph'`. Add fresh `sandbox_task` FK against `tasks.Task` per § 2.2. Drop the legacy `sandbox_task_id` and `sandbox_run_id` UUID columns outright — both were tied to the unshipped Redis-relay flow, no backfill needed. Single migration, no `SeparateDatabaseAndState` rename.
2. **`ee/hogai/sandbox/posthog_api.py`.** Typed HTTP client for `/api/projects/{tid}/tasks/*` endpoints with JWT.
3. **`ee/hogai/sandbox/context_wrapper.py`.** Per [`01_CONTEXT.md`](./01_CONTEXT.md) § 4.3.
4. **`ee/hogai/sandbox/system_prompt.py`.** Per [`04_PROMPTS.md`](./04_PROMPTS.md) § 6.
5. **`ee/hogai/sandbox/sse_relay.py` (skeleton).** Single-Run path (fresh-conversation fast path per § 4.2), ACP passthrough as default `event: message` with `data.type === 'notification'`. Forward `task_run_state` and `error` events from upstream as-is. Maintain the `{ runId → traceId }` map. No reconnect.
6. **View branch.** One `if` in `conversation_stream`.
7. **Frontend `sandboxStreamLogic.ts` (skeleton).** Pure parser; dispatches `agent_message_chunk`, `agent_message`, plus placeholder records for `tool_call` / `tool_call_update`. Fixture-driven unit tests.
8. **`maxThreadLogic.tsx` additive cases (subset).** Request body branch + the default `event: message` dispatch arm that switches on `data.type` for sandbox runs (`notification` → `ingestAcpFrame`; `task_run_state` / `permission_request` ignored at I1, handled at I2/I3). Existing LangGraph `case 'message'` handler untouched.
9. **Smoke MCP server.** A trivial heartbeat / echo MCP for end-to-end testing. Real tool surface follows in parallel via `03_RICH_UI.md` and `04_PROMPTS.md`.

End-to-end happy path testable after PR 8.

### Iteration 2 — sustained conversations

10. **Multi-Run chain walk in `bootstrap.py`.** Enumerate all Runs on the Task, concat `session_logs/`.
11. **`GET /conversations/{id}/log/` endpoint.** Reuses the chain walk; returns assembled `StoredLogEntry[]` JSON.
12. **Detail endpoint `messages` shape.** Empty array (or absent) for sandbox-runtime conversations; populated for LangGraph (unchanged).
13. **Follow-up routing.** `POST /command/` `user_message` for in-progress Runs; `POST /tasks/{id}/run/` with `resume_from_run_id` for terminal Runs.
14. **Cancel routing.** `POST /command/` `cancel`.
15. **Reconnect / backoff.** 5 attempts / 2s base / 30s cap. Constants in § 4.2.
16. **Error class ladder.** 401/403/404/406/other mapping per § 4.4.
17. **`maxThreadLogic.tsx` additive cases (rest).** Wire the sandbox `case 'message'` dispatch arm's `task_run_state` branch to `handleSandboxTerminalStatus`; wire `case 'error'` to `handleSandboxStreamError`.
18. **Frontend `maxLogic` history-load branching.** LangGraph reads `detail.messages`; sandbox calls `GET /log/` and feeds entries through `sandboxStreamLogic.ingestAcpFrame`.
19. **Telemetry parity.** `PROMPT_SENT`, `TASK_RUN_CANCELLED`, `PERMISSION_RESPONDED` events emitted from the sandbox branch with `execution_type: 'sandbox'` property.

End-to-end sustained-conversation experience testable after PR 18.

### Iteration 3 — production-ready

20. **`permission_request` ingest.** No new SSE event name — `data.type === 'permission_request'` already flows on the default `message` event per § 4.1; wire it through the existing dispatch arm to `sandboxStreamLogic.ingestPermissionRequest`.
21. **`maxThreadLogic.tsx` additive case (continued).** Activate the `task_run_state` and `permission_request` branches of the `case 'message'` dispatch arm; they were inert at I1.
22. **`POST /command/` `permission_response` routing.** Per § 5.5.
23. **`DangerousOperationApprovalCard` variant prop.** Cross-spec into `03_RICH_UI.md` § 5.
24. **Slash command runtime filter.** Per § 8 — `/init` and `/remember` show "not supported yet" for sandbox runtime; `/usage`, `/feedback`, `/ticket` unchanged.
25. **Concurrent terminal-then-resume race handling.** Confirm cloud-agent's duplicate `POST /tasks/{id}/run/` behavior first (idempotent vs. allow-both vs. error). If non-idempotent, add `SELECT FOR UPDATE` on the `Conversation` row inside the relay's follow-up branch to serialize the create.
26. **Pre-warming integration.** `POST /conversations/{id}/prewarm/` + `DELETE` endpoints per `05_SANDBOX.md` § 8.

Ready for broader internal release after PR 26.

### Parallel work (don't block on this checklist)

- **`03_RICH_UI.md`** registry skeleton + per-tool adapters — ships per-tool behind `posthog-ai-sandbox-tool-{slug}` flags. Can start as soon as I1 PR 5 is merged.
- **`04_PROMPTS.md`** MCP servers — `posthog-data`, `posthog-notebook`, etc. — independent stream.

---

## 12. Open questions

All originally-tracked questions have been resolved during planning. The bullets below capture the disposition for the record.

**Resolved decisions:**

- **#3 — Bootstrap fast path for fresh conversations.** Take it. New `just_created_run` gate in the relay skips § 4.2's multi-Run walk entirely when the request just created the Task + first Run. Spec'd inline in § 4.2.
- **#4 — `_meta.trace_id` propagation.** Verified in Twig — `claude-agent.ts:1593-1605` (`broadcastUserMessage`) builds `user_message_chunk` notifications without `_meta`; inbound `_meta` on `POST /command/ user_message` is ignored at `agent-server.ts:602`. Resolution: maintain a `{ runId → traceId }` map inside `sse_relay.py` and stamp `data.traceId` onto each forwarded envelope at emit time. No agent-server fork. Documented in § 4.1 and § 10.
- **#5 — Event-name convention.** Mirror PostHog Code exactly: default SSE `event: message` carries all data envelopes (discriminated by `data.type`); only `error` and `keepalive` are named events. Spec'd in § 4.1.
- **#2 (model migration shape) — drop UUIDs, fresh FK.** No in-place rename, no `SeparateDatabaseAndState`. The legacy `sandbox_task_id` / `sandbox_run_id` UUID columns are dropped outright in the migration that adds the new `sandbox_task` FK. Spec'd in § 2.2.

**Resolved as action items (no design change):**

- **#1 — `executor.py` repurpose vs leave.** Grep callers before I1 PR 5. If unused → repurpose. If used → leave and add `sse_relay.py` alongside.
- **#6 — Concurrent terminal-then-message races.** Already on the I3 plan (PR 25). Cloud-agent's duplicate-Run-create behavior must be confirmed first; if non-idempotent, `SELECT FOR UPDATE` on the `Conversation` row inside the relay's follow-up branch serializes the create. Ping the cloud-agent team early so I3 isn't blocked.
