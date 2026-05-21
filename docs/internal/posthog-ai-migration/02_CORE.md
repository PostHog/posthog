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

## 2. Model changes

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

The on-disk consequence is that we delete (or never write) the `sandbox_run_id` UUID column. The existing `sandbox_task_id` UUID column in `ee/hogai/sandbox/types.py` gets renamed/typed to a real FK; the `sandbox_run_id` UUID column gets dropped.

The existing `sandbox_task_id` UUID column was tied to the partial `executor.py` Redis flow. The migration plan:

1. **If `sandbox_task_id` is unused in production** (open question § 12.1 — confirm by grep + flag check first): rename via Django `RenameField` to `sandbox_task`, alter the type to `ForeignKey` in one migration with `state_operations` to preserve column data; `db_column="sandbox_task_id"` keeps the on-disk column name stable to avoid an `ALTER COLUMN`. The [`django-migrations`](https://docs.posthog.com/handbook/engineering/django-migrations) skill covers this `SeparateDatabaseAndState` pattern. Drop the `sandbox_run_id` column in the same migration.
2. **If still in use**: add `sandbox_task` FK alongside; backfill from the existing `sandbox_task_id` UUID; drop both old UUID columns in a follow-up after the soak.

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

## 3. The view — branching on `agent_runtime`

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

### 4.1 Wire format — passthrough

The conversation-stream emits one event type for the bulk of traffic, mirroring the cloud-agent upstream wire format:

```http
event: acp
id: <upstream Last-Event-ID, if any>
data: { "type": "notification", "timestamp": "...", "notification": { "method": "session/update", "params": { ... } } }
```

The `data` payload is the `StoredLogEntry` envelope (see cloud spec § 2.8 and `Twig/apps/code/src/shared/types/session-events.ts`). No frame-level translation. The frontend stream processor (§ 6) dispatches on `notification.method` + `notification.params.update.sessionUpdate` exactly as PostHog Code's renderer does.

Four convenience events are emitted **alongside** the raw stream so the existing surfaces in `maxThreadLogic` keep working without each one re-parsing ACP:

| Event                | When emitted                                                               | Payload                                                             | Frontend handler                                                                     |
| -------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `acp`                | Every ACP notification from the upstream stream                            | `StoredLogEntry`                                                    | The new `sandboxStreamLogic` (§ 6)                                                   |
| `permission_request` | Upstream emits a `permission_request` frame                                | `{ requestId, toolCall: {...}, options: [...] }`                    | The new `sandboxStreamLogic` _and_ the existing approval surface in `maxThreadLogic` |
| `status`             | Terminal `task_run_state` change (status ∈ {completed, failed, cancelled}) | `{ status: 'completed' \| 'failed' \| 'cancelled', errorMessage? }` | Existing `maxThreadLogic` Idle/Error transition                                      |
| `error`              | Upstream stream error (HTTP 401/403/404/406/other)                         | `{ errorTitle, errorMessage, retryable }`                           | Existing `maxThreadLogic` error handler                                              |

These four are not a "translation" — they're a thin convenience layer so the existing `maxThreadLogic` lifecycle hooks (already handling LangGraph status/error events) can keep firing. The `acp` event carries the full raw stream; the convenience events are derivable from it but are emitted separately so the consumer doesn't need to re-discover them.

Filtered/dropped at the relay (not forwarded):

- `keepalive` frames (cloud spec § 5.3): SSE-comment them or just drop. Connection liveness handled by downstream SSE library.
- _Nothing else._ Even noisy `_posthog/console`, `_posthog/progress`, `_posthog/sdk_session` frames are forwarded — the renderer filters at display time (and a debug toggle exposes them per Twig § 17 precedent).

### 4.2 Bootstrap (multi-Run chain + REST + SSE merge with content-dedup)

A conversation can have many Runs over its life (one per terminal+resume cycle — § 5.3). Each Run has its own NDJSON log in S3; together they form the full conversation history. The bootstrap assembles all of them into one chronological view for the frontend.

On open of a conversation with a non-null `sandbox_task`:

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

### 4.3 Reconnect / backoff

When the upstream SSE drops:

1. Refetch the Run via REST.
2. If terminal: emit a final `event: status` and close.
3. If non-terminal: capped exponential backoff up to 5 attempts (2s / 4s / 8s / 16s / 30s), then surface a retryable `event: error`.

If the downstream client (browser) disconnects, the relay closes the upstream connection too (no orphan upstream streams). The conversation's current Run continues to execute in the sandbox regardless — the next client reconnect re-bootstraps via § 4.2.

### 4.4 Error class mapping

Upstream HTTP status from `/runs/{rid}/` or `/stream/` → conversation-stream error envelope (cloud spec § 5.6):

| Upstream | `event: error` payload                                                   | Client response                     |
| -------- | ------------------------------------------------------------------------ | ----------------------------------- |
| 401      | `{ errorTitle: 'Cloud authentication expired', retryable: true }`        | Show retry; surface re-auth         |
| 403      | `{ errorTitle: 'Cloud access denied', retryable: true }`                 | Show retry                          |
| 404      | `{ errorTitle: 'Conversation backing run not found', retryable: false }` | Surface "create a new conversation" |
| 406      | `{ errorTitle: 'Cloud stream unavailable', retryable: true }`            | Show retry                          |
| other    | `{ errorTitle: 'Cloud stream failed', retryable: true }`                 | Auto-retry per § 4.3                |

### 4.5 Module layout

```
posthog/ee/hogai/sandbox/
    __init__.py
    types.py                ← existing
    mapping.py              ← existing
    executor.py             ← existing (Redis relay — see open question § 12)
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

### 4.6 Non-streaming history retrieval

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

### 4.7 Detail endpoint `messages` field — runtime-dependent

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

### 5.1 First message in a conversation

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

### 5.2 Follow-up message (in-progress Run)

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

### 5.3 Follow-up message (terminal Run → new Run)

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

### 5.4 Cancel

`POST /conversations/{id}/cancel/` (existing endpoint) → relay dispatches `POST /runs/{rid}/command/` with method `cancel`.

### 5.5 Permission response (approval)

Today's `DangerousOperationApprovalCard` posts back via an existing conversation endpoint. The sandbox branch routes that to `POST /runs/{rid}/command/` with method `permission_response` and the option payload:

```json
{ "requestId": "...", "optionId": "allow_once" | "reject" | "reject_with_feedback" | "...", "customInput": "..." }
```

Option-kind mapping is owned by [`03_RICH_UI.md`](./03_RICH_UI.md) § 5.

---

## 6. The frontend stream processor — `sandboxStreamLogic.ts`

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

## 7. `maxThreadLogic.tsx` — additive changes

The existing logic gains a runtime branch in three places. **No existing handler is modified**; the changes are alternative branches taken only when `conversation.agent_runtime === 'sandbox'`.

### 7.1 Request body builder

```ts
// before submitting a message
if (conversation.agent_runtime === 'sandbox') {
  return {
    content,
    trace_id,
    attached_context: posthogAIContextLogic.values.attachments,
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

The existing `eventsource-parser` loop already routes events by name. Add four handlers (additive case-block entries; existing ones unchanged):

```ts
case 'acp':
    sandboxStreamLogic.actions.ingestAcpFrame(JSON.parse(data))
    break

case 'permission_request':
    sandboxStreamLogic.actions.ingestPermissionRequest(JSON.parse(data))
    // existing approval surface in maxThreadLogic also reads pendingPermissionRequest
    break

case 'status':
    // sandbox path emits this on terminal task_run_state
    if (conversation.agent_runtime === 'sandbox') {
        handleSandboxTerminalStatus(JSON.parse(data))
    }
    break

case 'error':
    // sandbox path's error envelope shape matches today's `error` event well enough
    // — surface the same way as LangGraph errors
    if (conversation.agent_runtime === 'sandbox') {
        handleSandboxStreamError(JSON.parse(data))
    } else {
        // existing LangGraph error handler — UNCHANGED
    }
    break
```

The existing `case 'message'`, `case 'conversation_update'`, and `case 'sandbox'` (from the prior partial sandbox plumbing) keep firing for the LangGraph runtime and the legacy sandbox-debug surface respectively.

### 7.3 Thread state reads

The existing `threadGrouped` selector merges messages by `trace_id`. For sandbox conversations, the renderer (`Thread.tsx`) reads `sandboxStreamLogic.values.threadItems` instead — [`03_RICH_UI.md`](./03_RICH_UI.md) § 2 owns the dispatch.

---

## 8. Slash commands under sandbox runtime

| Command     | Sandbox runtime disposition                                | Notes                                                    |
| ----------- | ---------------------------------------------------------- | -------------------------------------------------------- |
| `/init`     | **No-op** with a "Not yet supported in sandbox AI" tooltip | Core memory dropped; see [`TODO.md`](./TODO.md) backfill |
| `/remember` | **No-op** with same tooltip                                | Same                                                     |
| `/usage`    | **Unchanged**                                              | Surfaces usage UI; independent of runtime                |
| `/feedback` | **Unchanged**                                              | Opens existing `FeedbackPrompt.tsx`                      |
| `/ticket`   | **Unchanged**                                              | Opens existing `TicketPrompt.tsx`                        |

Routing decision lives in `slash-commands.tsx`. Today's command-dispatch reducer gets a runtime-aware filter that hides or disables `/init` and `/remember` from the autocomplete for sandbox conversations. Existing LangGraph behavior preserved.

---

## 9. Multi-tab / shutdown

Two tabs open the same conversation. Each hits `/conversations/stream/` independently. The relay does **not** reference-count — each connection is its own upstream subscription. The cloud-agent SSE handles multiple subscribers natively (cloud spec § 5).

Client disconnect (browser close, navigation away): Django streaming response closes; relay aborts its upstream stream. The sandbox Run continues running independently. On reconnect, bootstrap (§ 4.2) catches up via `session_logs/` + new SSE.

---

## 10. Telemetry continuity

Existing analytics events (`PROMPT_SENT`, `TASK_RUN_CANCELLED`, `PERMISSION_RESPONDED`, etc.) fire from the same code paths as today. The sandbox path adds an `execution_type: 'sandbox'` property to each event — a new property on existing events, not a new event type. All dashboards that filter on event name keep working.

`trace_id` is generated server-side at message create, same as today. Threading it into ACP via `_meta.trace_id` on the `POST /command/` call lets every emitted notification carry it back, which the relay surfaces in the `StoredLogEntry`'s timestamp + metadata.

---

## 11. Migration checklist

PRs in this order (each ships behind `posthog-ai-sandbox` for internal users):

1. **Conversation model migration.** Add `agent_runtime` column with default `'langgraph'`. Convert existing `sandbox_task_id` UUID column to a `sandbox_task` FK against `tasks.Task` per § 2.2 (rename + `SeparateDatabaseAndState` if the column is unused; otherwise add new FK alongside and backfill). Drop the `sandbox_run_id` UUID column — it has no successor; `current_sandbox_run` is derived.
2. **`ee/hogai/sandbox/posthog_api.py`.** Typed HTTP client for `/api/projects/{tid}/tasks/*` endpoints with JWT.
3. **`ee/hogai/sandbox/context_wrapper.py`.** Per [`01_CONTEXT.md`](./01_CONTEXT.md) § 4.3.
4. **`ee/hogai/sandbox/system_prompt.py`.** Per [`04_PROMPTS.md`](./04_PROMPTS.md) § 6.
5. **`ee/hogai/sandbox/sse_relay.py`.** Bootstrap + reconnect + ACP passthrough.
6. **View branch.** One `if` in `conversation_stream`.
7. **Frontend `sandboxStreamLogic.ts`.** Pure parser, with fixture-driven unit tests.
8. **`maxThreadLogic.tsx` additive cases.** Request body + 4 event handlers.
9. **Tool-name registry + adapters.** Per [`03_RICH_UI.md`](./03_RICH_UI.md).
10. **Approval card variant.** Per [`03_RICH_UI.md`](./03_RICH_UI.md) § 5.
11. **Slash command runtime filter.** Per § 8.
12. **MCP servers** (per [`04_PROMPTS.md`](./04_PROMPTS.md) § 5) — rolled out tool-by-tool behind `posthog-ai-sandbox-tool-{slug}`.

Each PR can ship independently. The end-to-end happy path is testable after PR 8.

---

## 12. Open questions

1. **`executor.py` repurpose vs leave.** The existing `ee/hogai/sandbox/executor.py` runs a Redis-backed relay. Before writing `sse_relay.py`, grep for callers and confirm whether it's behind a separate flag with active users. If unused, replace its internals. If used, leave alone and add `sse_relay.py` alongside.
2. **`sandbox_task_id` / `sandbox_run_id` column reuse.** Confirm via git log + grep that these UUID columns aren't pinned to the Redis-relay flow. `sandbox_task_id` becomes the new FK either in place or alongside (§ 2.2). `sandbox_run_id` is dropped outright — derivation replaces it.
3. **Bootstrap vs straight-to-live for fresh conversations.** A brand-new conversation has no historical log to merge. Skip § 4.2 step 2's `session_logs/` pagination entirely in that case to save a round-trip. Easy gate: `if just_created_run: skip bootstrap`.
4. **`_meta.trace_id` propagation.** Confirm the cloud-agent relay surfaces `_meta` from inbound `POST /command/` calls onto outbound notifications. If not, we have to maintain a `{ runId → traceId }` map server-side and stamp it at emit time.
5. **`event: acp` vs `event: notification`.** The convenience name. PostHog Code calls them `notification`; cloud spec § 5.3 calls them `task_run_state`/`permission_request`/etc. when typed and "everything else" otherwise. We pick `acp` for clarity but it's bikeshed-able.
6. **Concurrent terminal-then-message races.** Two browser tabs send a follow-up at the same moment when the current Run is terminal. Both attempt to create a new Run via `POST /tasks/{id}/run/`. The cloud-agent's behavior on the duplicate-create needs to be checked: does it return the same Run (idempotent), create both (we'd see two parallel Runs on the same Task — both would resolve as "current" depending on millisecond ordering), or error? If it allows both, we need server-side coordination — `SELECT FOR UPDATE` on the `Conversation` row at the start of message handling — to serialize the create.
