# 02 — Core functionality (message routing endpoint + frontend stream processor)

> **Coexistence mode** ([`BACKWARD_COMPAT.md`](./BACKWARD_COMPAT.md)). LangGraph conversations stream today's wire format through Django (`POST /stream/`) and consume today's `maxThreadLogic` event handlers verbatim. Sandbox conversations route messages through Django (`POST /sandbox/`, non-streaming) and open SSE **directly** against the cloud-agent endpoint `/api/projects/{tid}/tasks/{taskId}/runs/{runId}/stream/` (the same endpoint PostHog Code consumes). The two paths share `maxThreadLogic`'s outer shell (thread state, send lifecycle) but split at the network layer.

This spec covers two surfaces:

1. The Django **message routing endpoint** `POST /api/environments/{tid}/conversations/{id}/sandbox/` for `agent_runtime === 'sandbox'`. Non-streaming. Wraps + dedupes + creates Run (or sends follow-up `POST /command/`) and returns `{task_id, run_id, ...}`.
2. The new frontend module that opens SSE against the cloud-agent endpoint, parses the wire format, and turns raw ACP into thread-shaped state.

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
| **I1 — vertical slice ("hello world")** | One user message → streamed response, end-to-end through the sandbox path (`POST /sandbox/` → frontend opens SSE directly against cloud-agent). Internal devs only. | § 2, § 3, § 4 (first-message branch of `POST /sandbox/`), § 4.1 (consume cloud-agent wire format), § 4.5, § 5.1, § 6.1–6.3 (SSE-owning logic + skeleton dispatch), § 7.1, § 7.3, partial § 11 | Multi-turn within a Run, resume across Runs, history retrieval for existing conversations, approvals, slash command gating, reconnect/backoff, pre-warming. Tool rendering = text-only placeholder; full registry runs in parallel via `03_RICH_UI.md` after I1 unblocks the wire format. |
| **I2 — sustained conversations** | Multi-turn, resume after terminal, reopening old conversations, reconnect resilience. | § 4 (follow-up branches), § 4.2 (multi-Run history via `GET /log/`), § 4.3 (frontend reconnect), § 4.4 (frontend error mapping), § 4.6 (`GET /log/` endpoint), § 4.7, § 5.2, § 5.3, § 5.4, § 6 (terminal-status + error handling), § 7.2, § 9, § 10 | Approvals, slash command gating, race-handling for terminal-then-resume, pre-warming. |
| **I3 — production-ready** | Approvals, slash command UX, race-hardening, pre-warming integration. | § 5.5, § 6 (`permission_request` ingest in `sandboxStreamLogic`), § 8, § 12 (race handling: cloud-agent dup-create idempotency + `SELECT FOR UPDATE` in `POST /sandbox/` if needed), integration with `05_SANDBOX.md` § 8 pre-warming | — |

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

Per CLAUDE.md, both `Task` and `TaskRun` already carry `team_id` for tenant isolation; the FK doesn't change that — the `POST /sandbox/` handler's permission check still happens against `request.user`'s team membership before any cross-table query.

### 2.3 Feature-flag resolution at create-time

In the conversation-create view (existing `/conversations/` POST or implicit on the first `/conversations/stream/` or `/conversations/sandbox/` call):

```python
if posthoganalytics.feature_enabled("posthog-ai-sandbox", user.distinct_id):
    conversation.agent_runtime = Conversation.AgentRuntime.SANDBOX
```

Once written, the flag is not re-evaluated. A user who loses the flag mid-conversation continues to see the existing chat on the sandbox runtime.

---

## 3. The view — runtime-split surfaces [I1]

The sandbox runtime does **not** stream through Django. Instead, message routing and SSE consumption are split:

- **LangGraph runtime** keeps `POST /api/environments/{tid}/conversations/{id}/stream/` — Django opens an SSE response and emits LangGraph's events. Unchanged.
- **Sandbox runtime** uses a new **non-streaming** routing endpoint `POST /api/environments/{tid}/conversations/{id}/sandbox/` that wraps + dedupes + creates a Run (or sends a `POST /command/`) and returns `{taskId, runId, traceId}`. The frontend then opens SSE **directly** against the cloud-agent endpoint `GET /api/projects/{tid}/tasks/{taskId}/runs/{runId}/stream/` — the same endpoint PostHog Code consumes (`Twig/apps/code/src/main/services/cloud-task/service.ts:593-598`). The endpoint is on PostHog cloud (same origin as Max), so session cookies authenticate the browser request natively. Confirmation owed: that DRF endpoint accepts session-cookie auth in addition to PostHog Code's OAuth bearer (default for `/api/projects/...` viewsets — see § 12).

Why split:

- The PostHog-cloud SSE bridge in `/api/projects/{tid}/tasks/{taskId}/runs/{runId}/stream/` already does reconnect, multi-subscriber fanout, terminal-status hoisting, and the `permission_request` envelope — building a second Django SSE relay just to mirror that would duplicate already-shipped code.
- Django doesn't tie up worker processes on long-lived SSE for sandbox conversations.
- Frontend gets to reuse PostHog Code's `cloud-task/service.ts` parsing + dedup + reconnect logic (port to the Kea logic in § 6).

Frontend dispatch in `maxThreadLogic.sendMessage`:

```python
# Backend view registration:

@api_view(["POST"])
def conversation_stream(request, conversation_id):
    """LangGraph-only — unchanged."""
    conversation = Conversation.objects.get(...)
    assert conversation.agent_runtime == Conversation.AgentRuntime.LANGGRAPH
    return langgraph_stream_response(request, conversation)


@api_view(["POST"])
def conversation_sandbox(request, conversation_id):
    """Sandbox-only — non-streaming routing endpoint (§ 4)."""
    conversation = Conversation.objects.get(...)
    assert conversation.agent_runtime == Conversation.AgentRuntime.SANDBOX
    return sandbox_message_response(request, conversation)
```

The LangGraph endpoint stays at `/stream/` byte-for-byte. The new sandbox endpoint at `/sandbox/` is purely additive. The frontend (`maxThreadLogic`) picks the endpoint based on `conversation.agent_runtime` at send time.

---

## 4. The sandbox message endpoint — `POST /sandbox/` [I1]

**Non-streaming.** Reads the request body, wraps + dedupes, creates the Run or sends a follow-up command, returns the IDs the frontend needs to open SSE.

```http
POST /api/environments/{tid}/conversations/{conversationId}/sandbox/
Cookie: <PostHog session>
{ "content": "Why did checkout drop?", "trace_id": "...", "attached_context": [ ... ] }
```

Response (HTTP 200):

```json
{
  "task_id": "uuid",
  "run_id": "uuid",
  "trace_id": "...",
  "run_status": "queued" | "in_progress",
  "just_created_run": true
}
```

The handler:

1. Read `attached_context` + `content` + `trace_id`.
2. Compute `prior_seen = collect_seen_entity_refs(conversation)` by walking prior `_posthog/user_message` log entries (one S3 read; cached per request).
3. `deduped = prune_repeated_entity_refs(attached_context, prior_seen)`; `wrapped = wrap_user_message(content, deduped)` ([`01_CONTEXT.md`](./01_CONTEXT.md) § 4.3).
4. Branch:
   - **First message in the conversation** (`conversation.sandbox_task` is NULL):
     - Build system prompt via `build_posthog_ai_system_prompt(...)` ([`04_PROMPTS.md`](./04_PROMPTS.md) § 6).
     - `POST /api/projects/{tid}/tasks/` to create the Task (no repository, no GitHub integration — [`04_PROMPTS.md`](./04_PROMPTS.md) § 2.3).
     - `POST /api/projects/{tid}/tasks/{taskId}/run/` with `pending_user_message: wrapped`, `state.attached_context: attached_context` (full undeduped list), `state.initial_permission_mode: "default"`, `state.systemPrompt: ...`.
     - Persist `conversation.sandbox_task = task`. `current_sandbox_run` falls out of the Task's reverse relation.
     - Set `just_created_run: true` in the response.
   - **Follow-up, current Run in-progress** (`run.status in {queued, in_progress}`):
     - `POST /api/projects/{tid}/tasks/{taskId}/runs/{runId}/command/` with `{"jsonrpc":"2.0","method":"user_message","params":{"content": wrapped, "_meta": {"attached_context": [...]}}}`.
     - Return the existing `task_id` / `run_id`; `just_created_run: false`.
   - **Follow-up, current Run terminal** (`run.status in {completed, failed, cancelled}`):
     - `POST /api/projects/{tid}/tasks/{taskId}/run/` with `state.resume_from_run_id: previous_run_id`, `pending_user_message: wrapped`, `state.attached_context`, `state.initial_permission_mode`, `state.systemPrompt`.
     - Return the **new** `task_id` (same) + `run_id` (new); `just_created_run: true`.
5. Update telemetry: `PROMPT_SENT` event with `{ trace_id, conversation_id, execution_type: 'sandbox', just_created_run }`.

The response is the contract the frontend's `sandboxStreamLogic` needs to know which Run to open SSE against. No frame relay — that's all client-side now (§ 6).

### 4.1 Wire format — consume cloud-agent's directly, as PostHog Code does [I1]

The frontend opens `GET /api/projects/{tid}/tasks/{taskId}/runs/{runId}/stream/` itself and consumes the cloud-agent's wire format verbatim (`Twig/apps/code/src/main/services/cloud-task/service.ts:585-690`). The wire format is **not** owned by this spec — it's whatever the cloud-agent endpoint emits, which PostHog Code already consumes. Default SSE `event: message` with `data.type` discrimination; named events `error` and `keepalive`:

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

| `data.type` (on default `message`) | Frontend handler                                                                          |
| ---------------------------------- | ----------------------------------------------------------------------------------------- |
| `notification`                     | `sandboxStreamLogic.ingestAcpFrame` (§ 6.3)                                               |
| `permission_request`               | `sandboxStreamLogic.ingestPermissionRequest` + surface to `DangerousOperationApprovalCard` |
| `task_run_state`                   | `sandboxStreamLogic.handleTerminalStatus` — drives Idle/Error transition                   |
| `keepalive`                        | Ignored                                                                                   |

| Named `event:` | Frontend handler                            |
| -------------- | ------------------------------------------- |
| `error`        | `sandboxStreamLogic.handleStreamError`      |
| `keepalive`    | Ignored                                     |

**`trace_id` propagation.** The agent-server does not thread inbound `_meta.trace_id` from `POST /command/` calls onto outbound notifications (verified in `Twig/packages/agent/src/adapters/claude/claude-agent.ts:1593-1605`). The frontend doesn't need it stamped — it issued the POST and already knows the `trace_id` it should associate with the open SSE for the current Run. Correlation, not stamping.

### 4.2 Bootstrap — REST history + open SSE [I2]

The frontend `sandboxStreamLogic` is now responsible for assembling history when a conversation re-opens. The pattern mirrors `Twig/apps/code/src/main/services/cloud-task/service.ts:440-556` for the single-Run case and adds the multi-Run chain via the server-side `/log/` endpoint (§ 4.6):

1. On conversation open with `conversation.sandbox_task != NULL`:
   - `GET /api/environments/{tid}/conversations/{id}/log/` returns the assembled chronological `StoredLogEntry[]` across all Runs on the Task, plus `current_run_status`. One round-trip; no multi-Run walk in the client.
   - Feed each entry through `ingestAcpFrame`. Same reducer code path as live events.
2. If `current_run_status` is non-terminal, open SSE against `/api/projects/{tid}/tasks/{taskId}/runs/{currentRunId}/stream/` with `?start=latest`. Apply content-dedup against entries we already ingested from `/log/` (cloud spec § 9.4 — Redis-stream IDs aren't comparable to S3-log IDs). Same `Twig/.../service.ts` dedup strategy.
3. If terminal, no SSE open. The view is read-only history.

**Fresh-conversation fast path.** When the POST `/sandbox/` response carries `just_created_run: true`, the frontend skips the `/log/` call entirely — there's nothing historical to assemble — and goes straight to SSE.

Constants (frontend-side; mirrored from PostHog Code):

```ts
const MAX_SSE_RECONNECT_ATTEMPTS = 5
const SSE_RECONNECT_BASE_DELAY_MS = 2_000
const SSE_RECONNECT_MAX_DELAY_MS  = 30_000
```

### 4.3 Reconnect / backoff — frontend-owned [I2]

Mirrors `Twig/apps/code/src/main/services/cloud-task/service.ts` reconnect logic. When SSE drops:

1. Refetch run via `GET /api/projects/{tid}/tasks/{taskId}/runs/{runId}/`.
2. If terminal: dispatch a final terminal-status action and close.
3. If non-terminal: capped exponential backoff up to 5 attempts (2s / 4s / 8s / 16s / 30s), then surface a retryable error to `maxThreadLogic`.

Browser disconnect (tab close, navigation away): the `EventSource` closes; the conversation's current Run continues in the sandbox regardless. The next reconnect re-bootstraps via `/log/` + SSE-open per § 4.2.

### 4.4 Error class mapping — frontend-owned [I2]

HTTP status from `/runs/{rid}/` or `/stream/` → user-visible error:

| Status | Error envelope                                                           | Client response                     |
| ------ | ------------------------------------------------------------------------ | ----------------------------------- |
| 401    | `{ errorTitle: 'Cloud authentication expired', retryable: true }`        | Show retry; refresh session         |
| 403    | `{ errorTitle: 'Cloud access denied', retryable: true }`                 | Show retry                          |
| 404    | `{ errorTitle: 'Conversation backing run not found', retryable: false }` | Surface "create a new conversation" |
| 406    | `{ errorTitle: 'Cloud stream unavailable', retryable: true }`            | Show retry                          |
| other  | `{ errorTitle: 'Cloud stream failed', retryable: true }`                 | Auto-retry per § 4.3                |

Cloud-agent emits some of these as `event: error` frames (per cloud spec § 5.6); for non-streamed errors (initial open failure, refetch failure), the frontend maps the HTTP status directly via the same table.

### 4.5 Module layout [I1 scaffold]

```
posthog/ee/hogai/sandbox/
    __init__.py
    types.py                ← existing
    mapping.py              ← existing
    executor.py             ← existing (Redis relay — § 12 action item: grep callers before I1 PR 5; repurpose if unused, leave otherwise)
    context_wrapper.py      ← new (01_CONTEXT § 4)
    system_prompt.py        ← new (04_PROMPTS § 6)
    message_view.py         ← new (POST /sandbox/ handler — this spec § 4)
    posthog_api.py          ← new (typed HTTP client for /api/projects/{tid}/tasks/*)
    log_assembler.py        ← new (multi-Run chain walker for GET /log/ — § 4.6)
```

No `sse_relay.py` — that was Option A, abandoned for the PostHog Code precedent. The streaming is entirely client-side now.

`message_view.py` is the entry point for `POST /sandbox/`. It owns:

- Reading the request body.
- Dedupe + wrap via `context_wrapper.py`.
- Run-create or `POST /command/` via `posthog_api.py`.
- Returning `{task_id, run_id, trace_id, run_status, just_created_run}`.

Stateless across requests; one handler call per HTTP request.

### 4.6 Non-streaming history retrieval — `GET /log/` [I2]

For history-only views (terminal conversation reopened to read; conversation-list preview snippets) and as the bootstrap call before opening SSE (§ 4.2):

```http
GET /api/environments/{tid}/conversations/{conversationId}/log/
Cookie: <PostHog session>
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

Implementation (`log_assembler.py`):

1. Enumerate the Task's Runs in chronological order:
   ```python
   runs = list(
       TaskRun.objects
       .filter(task_id=conversation.sandbox_task_id)
       .order_by("created_at")
       .values("id", "status", "created_at")
   )
   ```
2. For each Run, paginate `GET /api/projects/{tid}/tasks/{taskId}/runs/{runId}/session_logs/?limit=5000` until `X-Has-More: false`. Concatenate into a single chronological `StoredLogEntry[]`.
3. Return the buffer + `current_run_status` (the last Run's status).

**Long-conversation perf note.** A conversation with dozens of Runs needs dozens of paginated REST round-trips. Acceptable for the common case (1–3 Runs); becomes slow past ~10. Mitigations if it matters: parallelize the fetches with `asyncio.gather`, or cache a concatenated `StoredLogEntry[]` server-side keyed on the Task ID, invalidated when a new Run goes terminal. Defer until measured.

**Runtime guard.** When `conversation.agent_runtime === 'langgraph'`, the endpoint returns `400 Bad Request` with `{ "detail": "log endpoint is sandbox-runtime only; use GET /conversations/{id}/ for langgraph messages" }`. LangGraph conversations don't have ACP logs to read.

**Permission.** Same auth check as the existing conversation endpoints — team membership on the conversation's team. No new IDOR surface.

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
    // sandbox — REST call to assemble from S3 ACP logs
    const { entries, current_run_status } = await api.conversations.log(conversationId)
    entries.forEach((entry) => sandboxStreamLogic.actions.ingestAcpFrame(entry))
    // If still in_progress / queued, open SSE directly against the cloud-agent stream;
    // if terminal, this is a read-only view.
    if (!isTerminal(current_run_status) && detail.sandbox_task) {
        sandboxStreamLogic.actions.openSseForRun({
            taskId: detail.sandbox_task.id,
            runId: detail.sandbox_task.current_run_id,
        })
    }
}
```

The frontend opens SSE against `/api/projects/{tid}/tasks/{taskId}/runs/{runId}/stream/` itself (no Django proxy). The stream may emit historical frames since the Run started; `sandboxStreamLogic` content-dedups against the entries already ingested from `/log/` (serialized-JSON match, mirroring `Twig/.../service.ts:800`).

---

## 5. Lifecycle — message routing

### 5.1 First message in a conversation [I1]

```
client            Django (POST /sandbox/)            cloud-agent REST          cloud-agent SSE
  │                       │                                  │                          │
  ├── POST /sandbox/ ────▶│                                  │                          │
  │   { content,          │                                  │                          │
  │     attached_context, │                                  │                          │
  │     trace_id }        │                                  │                          │
  │                       │                                  │                          │
  │                       ├── wrap_user_message(...)         │                          │
  │                       │                                  │                          │
  │                       ├── POST /tasks/ ─────────────────▶│                          │
  │                       ◀── { task_id } ──────────────────┤                          │
  │                       │                                  │                          │
  │                       ├── POST /tasks/{id}/run/ ────────▶│                          │
  │                       │   { pending_user_message,        │                          │
  │                       │     state.attached_context,      │                          │
  │                       │     state.initial_permission_mode│                          │
  │                       │     state.systemPrompt }         │                          │
  │                       ◀── { run_id, status: queued } ───┤                          │
  │                       │                                  │                          │
  │                       ├── UPDATE conversation            │                          │
  │                       │   sandbox_task                   │                          │
  │                       │                                  │                          │
  ◀── 200 { task_id,      ┤                                  │                          │
  │       run_id,         │                                  │                          │
  │       trace_id,       │                                  │                          │
  │       run_status,     │                                  │                          │
  │       just_created:1 }│                                  │                          │
  │                                                          │                          │
  ├── GET /api/projects/{tid}/tasks/{task_id}/runs/{run_id}/stream/ ────────────────────▶│
  ◀── data: { type: notification, ... } ───────────────────────────────────────────────┤
  ◀── data: { type: notification, ... } ───────────────────────────────────────────────┤
  ◀── data: { type: task_run_state, status: completed } ───────────────────────────────┤
  ...
```

### 5.2 Follow-up message (in-progress Run) [I2]

```
  ├── POST /sandbox/ ────▶│                                  │                          │
  │   { content, ... }    │                                  │                          │
  │                       │                                  │                          │
  │                       ├── POST /runs/{id}/command/ ─────▶│                          │
  │                       │   { method: user_message,        │                          │
  │                       │     params: { content: wrapped,  │                          │
  │                       │       _meta: { attached_context }}}                         │
  │                       ◀── { result: { ... } } ──────────┤                          │
  │                       │                                  │                          │
  ◀── 200 { task_id,      ┤                                  │                          │
  │       run_id,         │                                  │                          │
  │       just_created:0 }│                                  │                          │
  │                                                          │                          │
  │   (existing SSE connection on /runs/{run_id}/stream/ keeps emitting; no re-open)    │
  ◀── data: { type: notification, ... } ───────────────────────────────────────────────┤
  ...
```

### 5.3 Follow-up message (terminal Run → new Run) [I2]

```
  ├── POST /sandbox/ ────▶│                                  │                          │
  │                       │   current_sandbox_run.status     │                          │
  │                       │   ∈ {completed, failed, cancelled}                          │
  │                       │                                  │                          │
  │                       ├── POST /tasks/{id}/run/ ────────▶│                          │
  │                       │   { state.resume_from_run_id,    │                          │
  │                       │     state.attached_context,      │                          │
  │                       │     state.systemPrompt,          │                          │
  │                       │     pending_user_message }       │                          │
  │                       ◀── { run_id: new, status: queued }┤                          │
  │                       │                                  │                          │
  ◀── 200 { task_id,      ┤  (new Run; current_sandbox_run                              │
  │       run_id: new,    │   resolves to it via the Task)                              │
  │       just_created:1 }│                                  │                          │
  │                                                          │                          │
  │   (close prior /runs/{old}/stream/ if still open)                                   │
  ├── GET /api/projects/{tid}/tasks/{task_id}/runs/{new_run_id}/stream/ ──────────────────▶│
  ◀── data: { type: notification, ... } ───────────────────────────────────────────────┤
  ...
```

### 5.4 Cancel [I2]

`POST /api/environments/{tid}/conversations/{id}/cancel/` (existing endpoint, sandbox branch) → handler dispatches `POST /api/projects/{tid}/tasks/{taskId}/runs/{runId}/command/` with `{"method": "cancel", "params": {}}`. Returns the new `run_status` (typically `cancelled`). The frontend SSE will then receive `data.type === 'task_run_state'` with `status: 'cancelled'` and close.

### 5.5 Permission response (approval) [I3]

Today's `DangerousOperationApprovalCard` posts back via an existing conversation endpoint. The sandbox branch routes that to `POST /api/environments/{tid}/conversations/{id}/permission/` which forwards as `POST /api/projects/{tid}/tasks/{taskId}/runs/{runId}/command/` with method `permission_response`:

```json
{ "requestId": "...", "optionId": "allow_once" | "reject" | "reject_with_feedback" | "...", "customInput": "..." }
```

Option-kind mapping is owned by [`03_RICH_UI.md`](./03_RICH_UI.md) § 5. The Django side stays thin — it's a routing wrapper, not a relay.

---

## 6. The frontend stream processor — `sandboxStreamLogic.ts` [I1 skeleton + SSE ownership; I2 + I3 expand dispatch]

A new Kea logic that **owns the SSE connection** to the cloud-agent stream endpoint, parses the wire format, and produces thread-shaped state. Separate from `maxThreadLogic` so the rendering layer can evolve without re-touching ACP parsing — but unlike Option A, it also owns the network connection (Django no longer relays).

### 6.1 Responsibilities

1. Own the `EventSource` (or `fetch`-based equivalent) against `GET /api/projects/{tid}/tasks/{taskId}/runs/{runId}/stream/`. Open on `openSseForRun`, close on `closeSse` or conversation change.
2. Reconnect / backoff loop per § 4.3 (5 attempts, 2s → 30s capped).
3. Refetch Run via REST after disconnect to detect terminal state per § 4.3.
4. Error class mapping per § 4.4.
5. Content dedup against history previously ingested from `GET /log/` (serialized-JSON match, mirroring `Twig/.../service.ts:800`).
6. Parse the wire format (default `event: message` + `data.type` discrimination; named `error` / `keepalive`).
7. Maintain a `Map<toolCallId, ToolInvocation>` reducer that merges `tool_call` (creation) + N × `tool_call_update` (status/content/progress updates) into one record.
8. Maintain an ordered append-only list of "thread items" the renderer consumes: text chunks, tool-invocation records, permission requests, mode changes, run-lifecycle markers.
9. Emit derived selectors (`thinkingMessage`, `currentRunStarted`, `lastTurnComplete`) `maxThreadLogic` and `Thread.tsx` can read.

It does **not**:

- Render anything (that's `Thread.tsx` + [`03_RICH_UI.md`](./03_RICH_UI.md)).
- Post messages (that's `maxThreadLogic.sendMessage` → `POST /sandbox/`).
- Walk multi-Run history (that's `GET /log/`, owned by `log_assembler.py` server-side).

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
  kind?: string // ACP toolCall.kind
  locations?: { path: string; line?: number }[]
  contentBlocks: unknown[] // accumulated ACP `content[]` from updates
}

interface SandboxStreamLogicValues {
  // SSE connection state
  sseStatus: 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed' | 'error'
  reconnectAttempt: number
  lastEventId?: string
  currentRunStatus?: 'queued' | 'in_progress' | 'completed' | 'failed' | 'cancelled'

  // Thread state
  toolInvocations: Map<string, ToolInvocation>
  threadItems: ThreadItem[]
  assistantMessageBuffer: { id: string; text: string; complete: boolean }[]
  pendingPermissionRequest?: PermissionRequestRecord
  currentMode?: string
  currentProgress?: string
  runStarted: boolean
  turnComplete: boolean

  // Dedup
  ingestedEntryHashes: Set<string>
}

interface SandboxStreamLogicActions {
  // SSE lifecycle
  openSseForRun: (payload: { taskId: string; runId: string; startLatest?: boolean }) => void
  closeSse: () => void
  // Frame ingestion (called both by the SSE listener and by /log/ replay)
  ingestAcpFrame: (entry: StoredLogEntry) => void
  ingestPermissionRequest: (record: PermissionRequestRecord) => void
  handleTerminalStatus: (status: { status, errorMessage? }) => void
  handleStreamError: (envelope: { errorTitle, errorMessage, retryable }) => void
  // Reset
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

## 7. `maxThreadLogic.tsx` — additive changes [I1 endpoint dispatch; I2 history-load branching]

The existing logic gains a runtime branch in two places. **No existing handler is modified**; the changes are alternative branches taken only when `conversation.agent_runtime === 'sandbox'`. The existing SSE event handlers (`case 'message'`, `case 'conversation_update'`, `case 'sandbox'`, `case 'error'`) all remain LangGraph-only — sandbox runs never enter the EventSource loop in `maxThreadLogic` because the SSE connection moves to `sandboxStreamLogic`.

### 7.1 Send-message endpoint dispatch

```ts
async function sendMessage({ content, trace_id }) {
  if (conversation.agent_runtime === 'sandbox') {
    // POST /sandbox/ — non-streaming routing endpoint
    const { task_id, run_id, run_status, just_created_run } = await api.conversations.sandbox(
      conversation.id,
      {
        content,
        trace_id,
        attached_context: posthogAiContextLogic.values.attachments,
      }
    )

    // Hand off to sandboxStreamLogic — it owns the SSE connection
    sandboxStreamLogic.actions.openSseForRun({
      taskId: task_id,
      runId: run_id,
      startLatest: !just_created_run, // fresh runs need everything from the top
    })

    // analytics fires server-side; client may also emit PROMPT_SENT
    return
  }

  // LangGraph path — UNCHANGED: POST /stream/ opens an SSE response
  const stream = await api.conversations.stream(conversation.id, {
    content,
    trace_id,
    ui_context: maxContextLogic.values.compiledContext,
    billing_context: maxBillingContextLogic.values.billingContext,
    contextual_tools: maxGlobalLogic.values.tools,
  })
  consumeLangGraphStream(stream)
}
```

The LangGraph path keeps its EventSource loop verbatim. The sandbox path replaces that loop with a single `POST` + hand-off to `sandboxStreamLogic.openSseForRun`.

### 7.2 History-load branching (conversation re-open)

When `maxLogic` loads an existing conversation, it picks the history-load path based on `agent_runtime`. See § 4.7 for the worked example — same control flow lives in `maxLogic`, not `maxThreadLogic`, but is called out here because it's the second runtime branch:

- **LangGraph** — `detail.messages` is populated by the detail endpoint; feed straight into thread state.
- **Sandbox** — call `GET /log/`, replay entries through `sandboxStreamLogic.ingestAcpFrame`, then (if non-terminal) `sandboxStreamLogic.openSseForRun({ taskId, runId, startLatest: true })`.

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

Two tabs open the same conversation. Each tab independently opens its own `EventSource` against `/api/projects/{tid}/tasks/{taskId}/runs/{runId}/stream/`. The cloud-agent endpoint handles multiple subscribers natively (cloud spec § 5). No Django process is tied up by the SSE — each browser holds its own connection.

Tab close / navigation away: the browser closes the `EventSource`; the conversation's current Run continues in the sandbox regardless. On the next visit (any tab), `sandboxStreamLogic` re-bootstraps via `GET /log/` + SSE-open per § 4.2.

Race when two tabs send a follow-up to the same conversation simultaneously while the current Run is terminal: both call `POST /sandbox/`. The Django handler is now the serialization point — see § 12 #6.

---

## 10. Telemetry continuity [I2]

Existing analytics events (`PROMPT_SENT`, `TASK_RUN_CANCELLED`, `PERMISSION_RESPONDED`, etc.) fire from the same code paths as today. The sandbox path adds an `execution_type: 'sandbox'` property to each event — a new property on existing events, not a new event type. All dashboards that filter on event name keep working.

`trace_id` is generated either client-side or server-side at message create. Since the SSE bypasses Django, **no server-side trace_id stamping is needed** — the frontend already knows the `trace_id` it associated with the current `POST /sandbox/` request and correlates incoming SSE frames with it locally. (Verified in Twig that the agent-server does not propagate inbound `_meta.trace_id` through to outbound notifications — `claude-agent.ts:1593-1605`, `agent-server.ts:602` — so the agent-server-side path would not have surfaced it anyway. Client-side correlation is the simpler answer.) The `{ runId → traceId }` map that Option A would have needed in Django disappears entirely.

---

## 11. Migration checklist

Each PR ships behind `posthog-ai-sandbox` for internal users. Grouped by iteration per the table in the **Iteration plan** section.

### Iteration 1 — vertical slice

1. **Conversation model migration.** Add `agent_runtime` column with default `'langgraph'`. Add fresh `sandbox_task` FK against `tasks.Task` per § 2.2. Drop the legacy `sandbox_task_id` and `sandbox_run_id` UUID columns outright — both were tied to the unshipped Redis-relay flow, no backfill needed. Single migration, no `SeparateDatabaseAndState` rename.
2. **`ee/hogai/sandbox/posthog_api.py`.** Typed HTTP client for `/api/projects/{tid}/tasks/*` endpoints (POST `/tasks/`, POST `/tasks/{id}/run/`, POST `/runs/{id}/command/`, GET `/runs/{id}/`, GET `/runs/{id}/session_logs/`) with sandbox JWT.
3. **`ee/hogai/sandbox/context_wrapper.py`.** Per [`01_CONTEXT.md`](./01_CONTEXT.md) § 4.3.
4. **`ee/hogai/sandbox/system_prompt.py`.** Per [`04_PROMPTS.md`](./04_PROMPTS.md) § 6.
5. **`ee/hogai/sandbox/message_view.py` — `POST /sandbox/` handler.** First-message path only (fresh-conversation fast path). Wraps + creates Task + Run; returns `{task_id, run_id, trace_id, run_status, just_created_run: true}`. Confirm `/api/projects/{tid}/tasks/.../stream/` accepts session-cookie auth before testing E2E (cloud-agents team ping — see § 12).
6. **View registration.** New `POST /api/environments/{tid}/conversations/{id}/sandbox/` route; LangGraph `/stream/` route unchanged.
7. **Frontend `sandboxStreamLogic.ts` (skeleton).** Owns the `EventSource` against `/api/projects/{tid}/tasks/{taskId}/runs/{runId}/stream/`. Parses `data.type === 'notification'`. Dispatches `agent_message_chunk`, `agent_message`, placeholders for `tool_call` / `tool_call_update`. No reconnect/backoff/dedup at I1; fixture-driven unit tests.
8. **`maxThreadLogic.tsx` send-message branch.** Sandbox runtime: POST `/sandbox/` → hand off to `sandboxStreamLogic.openSseForRun`. Existing LangGraph send-message path untouched.
9. **Smoke MCP server.** A trivial heartbeat / echo MCP for end-to-end testing. Real tool surface follows in parallel via `03_RICH_UI.md` and `04_PROMPTS.md`.

End-to-end happy path testable after PR 8 (first message of fresh conversation streams through cleanly).

### Iteration 2 — sustained conversations

10. **`POST /sandbox/` follow-up branches.** In-progress Run → `POST /runs/{id}/command/ user_message`; terminal Run → `POST /tasks/{id}/run/` with `resume_from_run_id`. Both branches return `{task_id, run_id, just_created_run}` for the frontend.
11. **`ee/hogai/sandbox/log_assembler.py`.** Multi-Run chain walker: enumerate Runs on the Task, paginate each Run's `session_logs/`, concat chronologically.
12. **`GET /conversations/{id}/log/` endpoint.** Calls `log_assembler.assemble(conversation)`; returns `{entries: StoredLogEntry[], has_more, current_run_status}` JSON.
13. **Detail endpoint `messages` shape.** Empty array (or absent) for sandbox-runtime conversations; populated for LangGraph (unchanged).
14. **`POST /conversations/{id}/cancel/` sandbox branch.** Dispatches `POST /command/ cancel`; returns new `run_status`.
15. **`sandboxStreamLogic` reconnect / backoff / dedup.** 5 attempts / 2s base / 30s cap; refetch run via REST on disconnect; content-dedup against `/log/`-ingested entries. Ports `Twig/apps/code/src/main/services/cloud-task/service.ts:440-690`.
16. **`sandboxStreamLogic` error class mapping.** 401/403/404/406/other → user-visible envelope per § 4.4.
17. **`sandboxStreamLogic` terminal-status handling.** `data.type === 'task_run_state'` → drive Idle/Error transition on `maxThreadLogic`.
18. **Frontend `maxLogic` history-load branching.** LangGraph reads `detail.messages`; sandbox calls `GET /log/` and feeds entries through `sandboxStreamLogic.ingestAcpFrame`, then opens SSE if non-terminal.
19. **Telemetry parity.** `PROMPT_SENT`, `TASK_RUN_CANCELLED`, `PERMISSION_RESPONDED` events emitted from the sandbox branch with `execution_type: 'sandbox'` property.

End-to-end sustained-conversation experience testable after PR 18.

### Iteration 3 — production-ready

20. **`sandboxStreamLogic` `permission_request` ingest.** Wire `data.type === 'permission_request'` to `ingestPermissionRequest` + surface `pendingPermissionRequest` to the approval card.
21. **`POST /conversations/{id}/permission/` sandbox branch.** Routes to `POST /command/ permission_response`; returns confirmation. Per § 5.5.
22. **`DangerousOperationApprovalCard` variant prop.** Cross-spec into `03_RICH_UI.md` § 5.
23. **Slash command runtime filter.** Per § 8 — `/init` and `/remember` show "not supported yet" for sandbox runtime; `/usage`, `/feedback`, `/ticket` unchanged.
24. **Concurrent terminal-then-resume race handling.** Confirm cloud-agent's duplicate `POST /tasks/{id}/run/` behavior first (idempotent vs. allow-both vs. error). If non-idempotent, add `SELECT FOR UPDATE` on the `Conversation` row inside the `POST /sandbox/` follow-up branch to serialize the create.
25. **Pre-warming integration.** `POST /conversations/{id}/prewarm/` + `DELETE` endpoints per `05_SANDBOX.md` § 8.

Ready for broader internal release after PR 25.

### Parallel work (don't block on this checklist)

- **`03_RICH_UI.md`** registry skeleton + per-tool adapters — ships per-tool behind `posthog-ai-sandbox-tool-{slug}` flags. Can start as soon as I1 PR 5 is merged.
- **`04_PROMPTS.md`** MCP servers — `posthog-data`, `posthog-notebook`, etc. — independent stream.

---

## 12. Open questions

All originally-tracked questions have been resolved during planning. The bullets below capture the disposition for the record.

**Architecture pivot — Option B (PostHog Code precedent):**

The relay design described in earlier drafts of § 4 is **abandoned**. Instead of Django relaying SSE from the cloud-agent endpoint to the browser, the frontend opens SSE directly against `/api/projects/{tid}/tasks/{taskId}/runs/{runId}/stream/` — the same endpoint PostHog Code consumes (`Twig/apps/code/src/main/services/cloud-task/service.ts:585-690`). Django's only sandbox-runtime endpoint is `POST /sandbox/`, which routes the message (wrap + dedupe + Run-create or follow-up command) and returns the IDs the frontend needs.

Wins: no Django SSE relay (no long-lived workers tied up); wire format = cloud-agent's exactly (no convenience layer to design); reconnect/backoff/dedup logic exists already in PostHog Code's `service.ts` (port to `sandboxStreamLogic`); no `{ runId → traceId }` map needed (frontend correlates locally). Loses: nothing we actually used — server-side frame observability isn't a requirement (durable persistence is already in S3 via `SessionLogWriter`).

**Resolved decisions:**

- **#2 (model migration shape) — drop UUIDs, fresh FK.** No in-place rename, no `SeparateDatabaseAndState`. The legacy `sandbox_task_id` / `sandbox_run_id` UUID columns are dropped outright in the migration that adds the new `sandbox_task` FK. Spec'd in § 2.2.
- **#3 — Bootstrap fast path for fresh conversations.** Take it. The `POST /sandbox/` response carries `just_created_run: true`; frontend skips `GET /log/` and goes straight to SSE. Spec'd inline in § 4.2.
- **#4 — `_meta.trace_id` propagation.** Verified in Twig — `claude-agent.ts:1593-1605` (`broadcastUserMessage`) builds `user_message_chunk` notifications without `_meta`. **With the Option B pivot the question becomes moot:** the frontend issues `POST /sandbox/`, knows the `trace_id` it sent, and correlates incoming SSE frames with it locally. No server-side stamping, no `{ runId → traceId }` map.
- **#5 — Event-name convention.** Mirror PostHog Code exactly: default SSE `event: message` carries all data envelopes (discriminated by `data.type`); only `error` and `keepalive` are named events. Spec'd in § 4.1.

**Resolved as action items:**

- **#1 — `executor.py` repurpose vs leave.** Grep callers before I1 PR 5. If unused → repurpose. If used → leave alone (no `sse_relay.py` is being created anymore, so the alongside-vs-replace question dissolves — just confirm nothing else relies on its current shape before touching it).
- **#6 — Concurrent terminal-then-message races.** Already on the I3 plan (PR 24). Cloud-agent's duplicate-Run-create behavior must be confirmed first; if non-idempotent, `SELECT FOR UPDATE` on the `Conversation` row inside the `POST /sandbox/` follow-up branch serializes the create. Ping the cloud-agent team early so I3 isn't blocked.
- **New — session-cookie auth on `/api/projects/{tid}/tasks/.../stream/`.** Option B assumes the cloud-agent stream endpoint accepts PostHog session cookies in addition to PostHog Code's OAuth bearer (the default for DRF endpoints under `/api/projects/...`). One-line confirmation with the cloud-agents team before I1 PR 7. If it doesn't, mint a short-lived bearer in `POST /sandbox/` and return it alongside `task_id` / `run_id`.
