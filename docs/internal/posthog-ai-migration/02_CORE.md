# 02 — Core functionality migration

This spec covers the transport layer for PostHog AI on top of the cloud-agent Task/Run model. It owns: chat lifecycle, streaming, history, follow-ups, queueing, cancel, approval wire flow, slash-command disposition, and tab-aware scene integration. Adjacent concerns are out of scope and live elsewhere: dynamic context payloads (`01_CONTEXT.md`), tool-call interception + rich UI renderers (`03_RICH_UI.md`), prompt composition (`04_PROMPTS.md`).

Anchor docs: [`00_OVERVIEW.md`](./00_OVERVIEW.md) for the high-level architecture and concept mapping; [`CLOUD_AGENTS_FRONTEND_SPEC.md`](../CLOUD_AGENTS_FRONTEND_SPEC.md) for the target REST + SSE protocol — referenced inline as "Twig § N".

All new code lives under `frontend/src/scenes/posthog-ai/`. The existing `frontend/src/scenes/max/` stays untouched until Phase 5 decommission.

---

## 1. Today: how the chat works end-to-end

### 1.1 maxLogic, maxThreadLogic, maxGlobalLogic responsibilities

The current Max stack splits cleanly into three keyed logics. Each one keeps a different lifetime and different ownership of state.

`maxLogic` (`frontend/src/scenes/max/maxLogic.tsx`) is the per-tab scene-level controller — keyed by `tabId`, mounted by `Max.tsx` via `BindLogic`. It owns: the input draft (`question`), the in-tab routing between *new chat / chat history / open thread* (`conversationId`, `conversationHistoryVisible`, `backToScreen`), the URL ↔ state binding for `/ai`, `/ai/history`, `/ai?chat=<id>` and `/ai?ask=<prompt>` via `tabAwareUrlToAction` / `tabAwareActionToUrl`, the `frontendConversationId` (UUID generated on the client to key `maxThreadLogic` before the backend has assigned a real conversation id), the active-streaming-threads counter that gates the tab icon, and headline / breadcrumb selectors. It also restores prompts and context from `sessionStorage` (`PENDING_AI_PROMPT_KEY`, `PENDING_MAX_CONTEXT_KEY`) on OAuth-redirect-style remounts. It does *not* speak HTTP itself; conversation history fetching is delegated up to `maxGlobalLogic`.

`maxThreadLogic` (`frontend/src/scenes/max/maxThreadLogic.tsx`, ~2200 lines) is the heart. It's keyed by `${conversationId}-${tabId}` so the same conversation in two tabs gets two logic instances that cross-sync via `afterMount` (`maxThreadLogic.tsx:1731-1748`). It owns: the message list (`threadRaw: ThreadMessage[]`), live streaming state (`streamingActive`, `cancelLoading`, `currentThinkingMessage`), the trace id, the agent mode (`agentMode`, `agentModeLockedByUser`, `isSandboxMode`), the message queue (`queuedMessages`, `queueLimit`, `queueingEnabled`), approvals (`pendingApprovalProposalId`, `pendingApprovalsData`, `resolvedApprovalStatuses`), tool-call updates (`toolCallUpdateMap`), sandbox entries (`sandboxEntries`), retry / cancel counters, and a grab-bag of selectors (`threadGrouped`, `threadLoading`, `inputDisabled`, `filteredCommands`, `submissionDisabledReason`, `activeMultiQuestionForm`, `activeDangerousOperationApproval`). The main streaming entry-point is the `streamConversation` listener (`:601-844`) which speaks `api.conversations.stream(...)` directly, feeding the response body to `eventsource-parser` and dispatching each parsed event into the reducer via `onEventImplementation` (`:1972-2165`).

`maxGlobalLogic` (`frontend/src/scenes/max/maxGlobalLogic.tsx`) is the singleton. It owns: the conversation history cache (`conversationHistory: ConversationDetail[]`), data-processing consent (`dataProcessingAccepted`, `liabilityNoticeDismissed`, `dataProcessingDismissed` — persisted to `localStorage`), the tool registry (`registeredToolMap`, `availableStaticTools`, `toolMap`, `tools`, `toolSuggestions`), side-panel handles (`openSidePanelMax`, `askSidePanelMax`), and a few derived selectors (`isOrganizationCreatedRecently`, `shouldShowLiabilityNotice`, `editInsightToolRegistered`).

### 1.2 Streaming via api.conversations.stream + eventsource-parser

The transport today is a single endpoint: `POST /api/environments/{team_id}/conversations/stream/`. The request body is built inside `askMax` / `streamConversation`:

```
{
  trace_id: uuid,
  content: string | null,
  conversation?: string,                       // backend id, or frontend uuid for first turn
  contextual_tools: Record<string, any>,       // from maxGlobalLogic.tools
  ui_context?: MaxUIContext,                   // compiledContext + per-call override
  billing_context?: MaxBillingContext,
  agent_mode?: AgentMode | null,
  is_sandbox?: boolean,
  resume_payload?:
    | { action: "approve"; proposal_id: string }
    | { action: "reject"; proposal_id: string; feedback?: string }
    | { action: "form"; form_answers: MultiQuestionFormAnswers }
    | { action: "dismiss_form" }
}
```

The response is `text/event-stream`. `streamConversation` reads `response.body.getReader()` directly, decodes via `TextDecoder`, and feeds chunks into a `createParser({ onEvent })` from `eventsource-parser` (`maxThreadLogic.tsx:659-682`). Each parsed event hits `onEventImplementation(event, data, ctx)` which switches on `event` (`AssistantEventType.{Conversation, Update, Message, Status, Approval, Sandbox}`) and reducer-actions accordingly:

- `Conversation` (only on first stream) — backend assigns a real id; we call `setConversation` and `updateGlobalConversationCache`.
- `Update` — `AssistantUpdateEvent | SubagentUpdateEvent`; appends a string under `toolCallUpdateMap[tool_call_id]`.
- `Message` — the big one. `RootAssistantMessage` (Human / Assistant / Tool / Failure). The handler dedups by id, replaces a temp message on completion, and triggers `setPendingApproval` if `ui_payload[tool].status === PENDING_APPROVAL_STATUS` (`:2044-2057`).
- `Status` — `AssistantGenerationStatusType.GenerationError` flips the last message's status to `'error'`.
- `Approval` — direct `PendingApproval` payload; stored via `addPendingApprovalData` + `setPendingApproval`.
- `Sandbox` — log entry from `ee/hogai/sandbox` runs, parsed via `parseLogEvent` from `products/tasks/frontend/lib/parse-logs`.

Failure modes are handled by a single exception handler around the whole reader loop (`:683-822`):

- `AbortError` (user cancellation) — `posthog.capture('max conversation turn completed', { status: 'cancelled' })`.
- Network errors — retry up to 15 times with linear backoff if conversation is still in-progress server-side, else surface "you appear to be offline".
- `ApiError 400 + attr: 'content'` — "message is too long".
- `ApiError 409` (already in progress) — set `cache.clearThreadOnReplay = true`, reconnect (the stream replays from event 0; rebuild the thread).
- `ApiError 429` — "you've reached the usage limit, try again {retryAfter}".
- `ApiError 402` — "your organization reached its AI credit usage limit".
- `ApiError 5xx` — "something is wrong with our servers".

On disconnect mid-turn (no error caught but `done`), the loop just exits and the listener decrements `activeStreamingThreads`. There's no out-of-band reconnect except via `reconnectToStream` (`:1135-1157`), which the `afterMount` calls when it sees `conversation.status === InProgress` and we're not already streaming.

### 1.3 Conversation lifecycle

`Conversation` (in `~/types`) is what comes back from `GET /conversations/`. `ConversationDetail` adds `messages: RootAssistantMessage[]` and `pending_approvals: PendingApproval[]`. The list endpoint returns shallow `Conversation`s; detail fetch returns `ConversationDetail`.

```
GET  /api/environments/{tid}/conversations/                  → { results: Conversation[] }
GET  /api/environments/{tid}/conversations/{cid}/            → ConversationDetail
POST /api/environments/{tid}/conversations/stream/           → SSE (described above)
POST /api/environments/{tid}/conversations/{cid}/cancel/     → 200
POST /api/environments/{tid}/conversations/{cid}/messages/   → append a message (for /usage and synthetic content)
```

`ConversationStatus` is `{ Idle, InProgress, Canceling, Failed }`. The frontend treats `InProgress` as "an SSE connection should be open"; on mount, `maxThreadLogic.afterMount` calls `reconnectToStream` if it observes `InProgress` without an active `cache.generationController`.

### 1.4 Queue endpoint (GET /conversations/{id}/queue/)

`POSTHOG_AI_QUEUE_MESSAGES_SYSTEM` flag gates a side-channel: while a turn is streaming, users can submit additional messages that go into a server-side queue.

```
GET    /conversations/{cid}/queue/                  → { messages: ConversationQueueMessage[], max_queue_messages: number }
POST   /conversations/{cid}/queue/                  → enqueue
PATCH  /conversations/{cid}/queue/{qid}/            → edit a queued message
DELETE /conversations/{cid}/queue/{qid}/            → cancel a single queued
DELETE /conversations/{cid}/queue/                  → clear queue
```

Backend processing of the queue happens in `process_chat_agent_activity`, which pops messages and starts a new workflow per queued item. Sandbox mode is special-cased — the frontend drains the queue in `completeThreadGeneration` (`maxThreadLogic.tsx:1186-1200`) because there's no backend workflow loop in sandbox.

This whole endpoint **goes away** in the new world (see § 6).

---

## 2. Tomorrow: the Task/Run model

### 2.1 Chat → Task mapping

One PostHog AI chat = one cloud `Task`. The Task's `title` is the chat title (server-set after the first turn, just like today). `task.description` is set to the *first* user prompt at task creation. `task.repository` and `task.github_integration` are `null`. The discriminator is `task.origin_product = "posthog_ai"`.

`Task.json_schema` and `Task.signal_report` stay `null`. We never set `internal: true` from this surface.

### 2.2 User turn → Run vs same-Run `user_message`

There are two distinct shapes for "the user just typed something":

1. **First message of a new chat** — must create both a Task and a Run. Sequence: `POST /tasks/` to mint the Task, then `POST /tasks/{id}/run/` with `pending_user_message: <prompt>`, `mode: "interactive"`, `environment: "cloud"`, `initial_permission_mode: <default>`. The agent-server picks up `state.pending_user_message` at session init (Twig § 10.6) and submits it as the initial ACP prompt. Clear `pending_user_message` after consumption via `state_remove_keys`.

2. **Follow-up while the current Run is non-terminal** — `POST /tasks/{id}/runs/{rid}/command/` with method `user_message`, body `{ jsonrpc: "2.0", method: "user_message", params: { content: <string-or-blocks> } }`. The same Run continues; the agent-server handles the new prompt as a fresh ACP `prompt()` call within the same session.

3. **Follow-up after the current Run reached terminal state** — `POST /tasks/{id}/run/` again, with `resume_from_run_id: <prevRunId>` and `pending_user_message: <prompt>`. A new Run is created; the agent-server reads `state.resume_from_run_id` (Twig § 2.5, § 10.6) and rehydrates the prior conversation history (`resumeFromLog`) before submitting the new user message. From the user's perspective the chat is continuous — same Task, same `taskId` in URL.

The third pattern is novel relative to today's Max, which silently keeps streaming through the same `conversationId` regardless of whether the previous turn completed. The new model gives us a natural per-attempt boundary for cost accounting, model switching, and "this whole turn failed, retry it" without losing context.

### 2.3 Resume after terminal

Mirrors `resumeCloudRun` in `Twig/apps/code/src/renderer/features/sessions/service/service.ts:1894-2039`. The resume path is purely a transport-level concern: the user sees the same chat, the agent sees a new session that has been told to rehydrate from the prior log. No UI affordance.

Critical detail: we **do not** carry over per-Run config to the new Run blindly. We do propagate (Twig § 13.13):

- `state.run_source` (always `"manual"` for PostHog AI today, but propagated for future signal_report integration).
- `state.signal_report_id` if present.
- Prior `runtime_adapter`, `model`, `reasoning_effort` (read from `previousRun.runtime_adapter` etc., not `state`).
- `state.initial_permission_mode` (the user can't change it mid-Task, so we just re-pass the original).

We **do not** propagate `pr_authorship_mode` (irrelevant for PostHog AI — no PR), `branch`, or any git-related state.

### 2.4 Origin-product discriminator

`origin_product = "posthog_ai"` is the cleanest separator. The same field is already used to distinguish `"user_created"`, `"error_tracking"`, `"session_summaries"`, etc. (Twig § 2.3). The backend filter on `GET /tasks/?origin_product=posthog_ai` is what we use for chat history (§ 3.2).

There's an open question (Overview § 9.1) of whether the Task model should be extended further (e.g. a separate `ChatTask` subclass). For this spec we assume **option A: extend the existing Task model with nullable `repository` and `github_integration`, plus the existing `origin_product`**. Lower-risk and lets us share the entire cloud-agent infrastructure on day one.

---

## 3. Task model dependencies

### 3.1 Required Task fields (nullable repository, github_integration)

Frontend-visible Task shape (from Twig § 2.3) needs the following be acceptable on create:

```ts
interface CreatePostHogAiTaskBody {
  title: string                                  // initially set from first ~80 chars of prompt
  description: string                            // the user's first prompt verbatim
  origin_product: 'posthog_ai'
  repository: null                               // explicit null, not omitted
  github_integration: null
  github_user_integration: null
}
```

Backend changes (`02_CORE` owns: documenting; backend team owns: implementing):

- `posthog/models/task.py` (or wherever Task lives in `Twig/posthog`/products): permit `repository = None` when `origin_product = "posthog_ai"`. Today `repository` is non-null. Migration: `ALTER TABLE ... ALTER COLUMN repository DROP NOT NULL`.
- `posthog/api/tasks/serializers.py`: `validate(...)` allows the new shape; reject `repository = None` for any `origin_product` that's *not* in `{"posthog_ai"}` (preserve existing constraints for `"user_created"` etc.).
- The agent-server's `buildSessionSystemPrompt` already supports "No Repository Mode" (Twig § 10.5; `agent-server.ts:1529-1726`) — we don't ship any new sandbox-side code for this.

### 3.2 GET /tasks/ filter by origin_product

Chat history is a paginated list, sorted descending by `updated_at`. The backend filter should accept `origin_product=posthog_ai` and ignore tasks belonging to other product surfaces.

```
GET /api/projects/{tid}/tasks/?origin_product=posthog_ai&limit=20&offset=0
```

Sort: `updated_at DESC` (chronologically newest at the top — matches today's `mergeConversationHistory` sort by `updated_at` in `maxLogic.tsx:951-955`). The page size should be 20 to start; the existing endpoint already returns either `{ results: Task[] }` or a bare array (Twig § 4.2) so the client should tolerate both for backward-compat.

**Backend dependency**: confirm `?origin_product=` query-string filter is implemented on `GET /tasks/`. Twig's Task list view (`renderer/features/sidebar/.../TaskIcon.tsx` consumers) doesn't filter by origin today, so this may be a small new piece. If not present, this is a blocker for Phase 1.

### 3.3 Backend pre-interpolation of systemPrompt at Run-create

Out of this spec's scope (lives in `04_PROMPTS.md`), but worth noting: when we `POST /tasks/{id}/run/`, the backend must resolve `core_memory`, `billing_context`, `groups_prompt`, `agent_mode` defaults, and any other today-server-resolved pieces, then bake them into the systemPrompt that the agent-server reads at boot (Twig § 10.5 step 5). The transport layer here only needs to know: **we never pass these on the wire from the browser to PostHog cloud**. This is a clean break from today's per-turn `billing_context` field in the `stream/` body.

---

## 4. New logic layout

The new code lives in `frontend/src/scenes/posthog-ai/`. Four Kea logics, one scene file, one URL-binding adapter.

### 4.1 posthogAiLogic (history, current task)

`frontend/src/scenes/posthog-ai/posthogAiLogic.ts`. Keyed by `tabId` (same pattern as `maxLogic`). Replaces `maxLogic.tsx`.

Responsibilities:

- Per-tab `question` draft and submit-trigger.
- Active `taskId` (the current chat — renamed from `conversationId`).
- `taskHistoryVisible` (chat history pane open).
- `frontendTaskId` for new-chat keying (UUID generated client-side, dropped once the backend Task id arrives).
- Tab-aware URL bindings: `/posthog-ai/`, `/posthog-ai/history`, `/posthog-ai/?chat=<taskId>`, `/posthog-ai/?ask=<prompt>`.
- Loading `taskHistory` from `posthogAiGlobalLogic`.
- The `activeStreamingTasks` counter that drives the tab loading icon (mirror of today's `activeStreamingThreads`).
- `breadcrumbs` selector.
- `headline` / `chatTitle` selectors. Headlines are deterministic from `taskId.slice(-N)`; `chatTitle` is whatever the backend put in `Task.title`, falling back to "New chat".

Skeleton (pseudocode — interfaces over types per project conventions):

```ts
interface PostHogAiLogicProps {
  tabId: string | 'sidepanel'
}

interface PostHogAiLogicValues {
  question: string
  taskId: string | null                          // backend Task id (uuid)
  frontendTaskId: string                         // uuid generated client-side until backend assigns one
  taskHistoryVisible: boolean
  backToScreen: 'history' | null
  activeStreamingTasks: number
  task: Task | null                              // looked up from taskHistory by id
  taskLoading: boolean
  threadVisible: boolean
  chatTitle: string | null
  threadLogicKey: string                         // taskId ?? frontendTaskId
  threadLogicProps: PostHogAiThreadLogicProps
  breadcrumbs: Breadcrumb[]
}

interface PostHogAiLogicActions {
  setQuestion: (q: string) => { question: string }
  askPostHogAi: (prompt: string | null, addToThread?: boolean, uiContext?: Partial<PostHogAiUIContext>) => { ... }
  openChat: (taskId: string) => { taskId: string }
  setTaskId: (taskId: string) => { taskId: string }
  startNewChat: () => true
  toggleTaskHistory: (visible?: boolean) => { visible?: boolean }
  goBack: () => true
  setBackScreen: (screen: 'history') => { screen: 'history' }
  focusInput: () => true
  incrActiveStreamingTasks: () => true
  decrActiveStreamingTasks: () => true
  setAutoRun: (autoRun: boolean) => { autoRun: boolean }
}
```

The implementation closely mirrors `maxLogic`'s structure. Two notable differences:

- The URL-restored `chat=<id>` value is the *backend Task uuid*, not a frontend-generated value. When the user submits the first message of a new chat with `frontendTaskId` in the URL, we replace the URL with the real `taskId` once `POST /tasks/` returns. Today's `setConversationId` listener (`maxLogic.tsx:658-665`) already does this with `{ replace: true }`; port the same pattern.
- The `loadConversation` polling listener (today's `pollConversation`) is removed. The new world streams from `_posthog/run_started` onward; there's no "is the backend done generating?" gap to poll across.

### 4.2 posthogAiThreadLogic (per-Task: messages, ui state)

`frontend/src/scenes/posthog-ai/posthogAiThreadLogic.ts`. Keyed by `${taskId}-${tabId}`. Replaces `maxThreadLogic.tsx` (which is ~2200 lines and gets broken apart — the streaming half moves to `runWatcherLogic`).

Responsibilities:

- The thread message model: `messages: ThreadMessage[]` derived from the persisted log + live ACP events (§ 7).
- UI selectors: `threadGrouped`, `threadLoading`, `inputDisabled`, `submissionDisabledReason`, `filteredCommands`, etc.
- Pending approval state and approval-decision dispatch (§ 6.7) — same component (`DangerousOperationApprovalCard`), different wiring.
- Client-side message queue (§ 6.3, § 6.4) — replaces the server queue endpoint.
- Active Run for this Task: `currentRunId: string | null`.
- Cancellation control surface — calls `runWatcherLogic({ taskId, runId }).actions.cancelRun()`.
- Resume orchestration — owns the "is the current Run terminal?" decision and calls into `resumeRun()`.
- Slash command dispatch (§ 8).
- Trace-id surfacing for the UI (`traceId`, derived from `currentRunId`).
- Reading from `runWatcherLogic`: subscribes to the watcher for the current Run via `connect`, hoists the watcher's `messages`/`status`/`permissionRequest`/`errors` into this logic's state.

It does **not** speak HTTP directly except for the Task-create + Run-start + Run-resume calls — all event consumption flows through `runWatcherLogic`.

Sketch:

```ts
interface PostHogAiThreadLogicProps {
  tabId: string
  taskId: string                                 // backend or frontendTaskId
  task?: Task | null
}

interface PostHogAiThreadLogicValues {
  task: Task | null
  currentRunId: string | null
  messages: ThreadMessage[]                       // post-folding (see § 7)
  queuedMessages: QueuedPrompt[]                  // client-side, see § 6.3
  pendingApprovalRequestId: string | null
  pendingPermissionRequest: CloudTaskPermissionRequestUpdate | null
  runStatus: TaskRunStatus | null
  isPromptPending: boolean                        // a user_message in flight, awaiting turn_complete
  isInitializing: boolean                         // `queued | in_progress + no run_started yet`, see § 9.1
  cancelLoading: boolean
  errorOverlay: CloudTaskConnectionError | null   // surfaced verbatim from watcher
  traceId: string | null
  threadLoading: boolean                          // streamingActive || queued || in_progress-without-handshake
  threadGrouped: ThreadMessage[]                  // injected thinking message, tool_call status enhancement
  inputDisabled: boolean
  submissionDisabledReason: string | undefined
  filteredCommands: SlashCommand[]
  isSandboxMode: boolean                          // always true in new world — kept as a selector for compatibility
}

interface PostHogAiThreadLogicActions {
  askPostHogAi: (prompt: string, addToThread?: boolean) => { ... }     // entry point
  sendFollowUp: (prompt: string) => { prompt: string }                 // POST /command/ user_message
  resumeAfterTerminal: (prompt: string) => { prompt: string }          // POST /tasks/{id}/run/ + resume_from_run_id
  cancelRun: () => true
  respondToPermission: (requestId: string, optionId: string, customInput?: string) => { ... }
  enqueueQueuedMessage: (prompt: string) => { prompt: string }
  consumeQueuedMessages: () => true                                    // called on turn_complete
  appendMessage: (message: ThreadMessage) => { message: ThreadMessage }
  applyWatcherUpdate: (update: CloudTaskUpdatePayload) => { update: ... }
  setCurrentRunId: (runId: string | null) => { runId: string | null }
  setIsInitializing: (value: boolean) => { value: boolean }
  startNewChat: () => true                                             // also clears queue, traceId, etc.
}
```

### 4.3 posthogAiGlobalLogic (tool registry, project-level cache)

`frontend/src/scenes/posthog-ai/posthogAiGlobalLogic.ts`. Singleton. Replaces `maxGlobalLogic`.

Responsibilities that survive identically:

- `dataProcessingAccepted`, `dataProcessingDismissed`, `liabilityNoticeDismissed`.
- `registeredToolMap`, `availableStaticTools`, `toolMap`, `tools`, `toolSuggestions` — the tool registry consumed by `usePostHogAiTool` (defined in `03_RICH_UI.md`).
- Side-panel opening helpers (`openSidePanelPostHogAi`, `askSidePanelPostHogAi`).

Responsibilities that change:

- `conversationHistory` → `taskHistory: Task[]` with the same merge / sort semantics.
- The `loadConversation` loader is replaced with `loadTask(taskId)` that hits `GET /tasks/{taskId}/` + `GET /tasks/{taskId}/runs/?limit=1`. The list loader becomes `loadTaskHistory` → `GET /tasks/?origin_product=posthog_ai`.
- A new `loadRun(taskId, runId)` loader for resume / direct deep-linking.

Important: `posthogAiGlobalLogic` should *not* own per-Run SSE connections — that's `runWatcherLogic`. It only caches the REST-side metadata.

### 4.4 runWatcherLogic (per-Run: SSE, dedup, reconnect)

`frontend/src/scenes/posthog-ai/runWatcherLogic.ts`. Keyed by `${taskId}:${runId}`. **Reference-counted** — multiple mounts (same key) share one SSE stream and one bootstrap pass.

This is the Kea port of `Twig/apps/code/src/main/services/cloud-task/service.ts`. Same state machine, same `WatcherState`, same bootstrap dance — but expressed as Kea reducers / listeners instead of an injectable class.

Public surface from the watcher's perspective:

- **Inputs**: `apiHost`, `teamId`, `taskId`, `runId`. Wired from `getCloudCommandAuth()` (port the helper from desktop renderer) — for PostHog AI in-browser, these come from window context and `currentTeam` / `currentRegion` selectors.
- **Outputs (selectors)**: `status: TaskRunStatus`, `stage`, `output`, `errorMessage`, `branch`, `messages: ThreadMessage[]` (folded from log entries — see § 7), `permissionRequest: CloudTaskPermissionRequestUpdate | null`, `connectionError: CloudTaskConnectionError | null`, `isBootstrapping`.
- **Actions**: `subscribe`, `unsubscribe`, `retry`, `sendCommand({ method, params })`.

The watcher emits a stream of `CloudTaskUpdatePayload` (Twig § 2.8) which `posthogAiThreadLogic` folds into its `messages` reducer. Concretely we expose a `latestUpdate: CloudTaskUpdatePayload | null` selector that fires through `subscriptions` into the thread logic — much cleaner than wiring an `EventEmitter` into Kea.

Full layout in § 5.

---

## 5. The SSE watcher — porting cloud-task/service.ts to Kea

The Twig desktop `CloudTaskService` class becomes a keyed Kea logic. The mechanical translation:

| Class member | Kea equivalent |
|---|---|
| `watchers: Map<string, WatcherState>` | Each watcher is its own keyed logic instance; ref-count is `subscriberCount` in the logic's `cache`. |
| `watcher.sseAbortController` | `cache.sseAbortController` |
| `watcher.reconnectTimeoutId` / `batchFlushTimeoutId` | Use `cache.disposables.add(...)` from `frontend/src/kea-disposables.ts` (the project provides a disposables plugin that auto-cleans on `beforeUnmount` and auto-pauses on hidden tabs — see the `using-kea-disposables` skill). |
| `watcher.pendingLogEntries`, `bufferedLogBatches`, `emittedLogEntries` | Reducers (see § 5.1). |
| `watcher.lastEventId` etc. | Reducers. |
| `emit(CloudTaskEvent.Update, payload)` | Listener that fires an `applyUpdate(payload)` action; subscribers (`posthogAiThreadLogic`) read via the `latestUpdate` selector + `subscriptions`. |

### 5.1 WatcherState reducers

```ts
interface RunWatcherLogicValues {
  // Stable
  taskId: string
  runId: string
  apiHost: string
  teamId: number
  subscriberCount: number

  // Liveness
  isBootstrapping: boolean
  hasEmittedSnapshot: boolean
  failed: boolean
  needsPostBootstrapReconnect: boolean
  needsStopAfterBootstrap: boolean

  // SSE position
  lastEventId: string | null
  reconnectAttempts: number

  // Run state mirrors
  lastStatus: TaskRunStatus | null
  lastStage: string | null
  lastOutput: Record<string, unknown> | null
  lastErrorMessage: string | null
  lastBranch: string | null
  lastStatusUpdatedAt: string | null

  // Log buffers
  pendingLogEntries: StoredLogEntry[]              // not yet flushed
  bufferedLogBatches: StoredLogEntry[][]           // held during bootstrap
  emittedLogEntries: StoredLogEntry[]              // already pushed to subscribers
  totalEntryCount: number

  // Output
  latestUpdate: CloudTaskUpdatePayload | null      // selectors fire when this changes
  permissionRequest: CloudTaskPermissionRequestUpdate | null
  connectionError: CloudTaskConnectionError | null
}
```

Reducers map closely to `cloud-task/service.ts:73-99`:

```ts
reducers({
  subscriberCount: [0, {
    subscribe: state => state + 1,
    unsubscribe: state => Math.max(state - 1, 0),
  }],
  isBootstrapping: [false, {
    startBootstrap: () => true,
    finishBootstrap: () => false,
    failWatcher: () => false,
  }],
  hasEmittedSnapshot: [false, {
    emitSnapshot: () => true,
    retry: () => false,
  }],
  lastEventId: [null as string | null, {
    setLastEventId: (_, { id }) => id,
    retry: () => null,
  }],
  reconnectAttempts: [0, {
    incrementReconnectAttempt: state => state + 1,
    resetReconnectAttempts: () => 0,
  }],
  lastStatus: [null as TaskRunStatus | null, {
    applyTaskRunState: (_, { state }) => state.status ?? _,
  }],
  // ...etc., mirroring WatcherState
})
```

### 5.2 Bootstrap (REST + SSE merge)

Pseudocode for the bootstrap listener, ported from `bootstrapWatcher` (`service.ts:440-556`):

```ts
listeners(({ actions, values, cache }) => ({
  startBootstrap: async () => {
    actions.resetFailed()
    actions.resetNeedsPostBootstrapReconnect()

    const run = await api.tasks.getRun(values.taskId, values.runId).catch(handleFetchError)
    if (!run) return                                   // failWatcher already dispatched

    actions.applyTaskRunState(run)

    if (isTerminalStatus(run.status)) {
      const log = await fetchAllSessionLogs(values.taskId, values.runId)
      if (!log) return actions.failWatcher({ title: 'Failed to load task history', ... })
      actions.emitSnapshot({
        kind: 'snapshot',
        newEntries: log,
        totalEntryCount: log.length,
        status: run.status, stage: run.stage, output: run.output,
        errorMessage: run.error_message, branch: run.branch,
      })
      return                                            // No SSE for terminal runs
    }

    // Non-terminal: open SSE first, then paginate session_logs in parallel.
    actions.startBootstrapMode()
    actions.connectSse({ startLatest: true })
    const log = await fetchAllSessionLogs(values.taskId, values.runId)
    if (!log) return actions.failWatcher({ title: 'Failed to load run history', ... })

    // Live entries that arrived during the fetch sit in values.pendingLogEntries
    // and values.bufferedLogBatches. Snapshot first, then drain.
    actions.flushLogBatchIntoBuffer()
    actions.emitSnapshot({ ... })                       // status mirrors from REST
    actions.finishBootstrap()
    actions.drainBufferedLogBatches(log)

    if (values.needsStopAfterBootstrap || isTerminalStatus(values.lastStatus)) {
      actions.stopWatcher()
      return
    }
    if (values.needsPostBootstrapReconnect) {
      actions.scheduleReconnect({ countAttempt: false })
    }
    actions.verifyPostBootstrapStatus()
  },
}))
```

`fetchAllSessionLogs` paginates `GET /tasks/{tid}/runs/{rid}/session_logs/?limit=5000&offset=N` until `X-Has-More: false` (Twig § 4.2). Use 5000 to match desktop.

### 5.3 Content-dedup against historical log

Direct port of `drainBufferedLogBatches` (`service.ts:793-839`). The rationale (Twig § 9.4): SSE event ids are Redis stream ids that **don't exist** in the S3 NDJSON log. The only reconcilable key is the serialized JSON payload itself.

```ts
drainBufferedLogBatches: (historicalEntries: StoredLogEntry[]) => {
  const historicalCounts = new Map<string, number>()
  for (const entry of historicalEntries) {
    const k = JSON.stringify(entry)
    historicalCounts.set(k, (historicalCounts.get(k) ?? 0) + 1)
  }
  for (const batch of values.bufferedLogBatches) {
    const deduped = batch.filter(entry => {
      const k = JSON.stringify(entry)
      const remaining = historicalCounts.get(k) ?? 0
      if (remaining <= 0) return true
      historicalCounts.set(k, remaining - 1)
      return false
    })
    if (deduped.length === 0) continue
    actions.emitLogs(deduped)
  }
  actions.clearBufferedLogBatches()
}
```

### 5.4 Reconnect / backoff

Constants identical to desktop (`service.ts:21-26`):

```
MAX_SSE_RECONNECT_ATTEMPTS = 5
SSE_RECONNECT_BASE_DELAY_MS = 2_000
SSE_RECONNECT_MAX_DELAY_MS = 30_000
EVENT_BATCH_FLUSH_MS = 16
EVENT_BATCH_MAX_SIZE = 50
SESSION_LOG_PAGE_LIMIT = 5_000
```

The backoff formula: `delay = min(BASE * 2^(attempts-1), MAX)`. After 5 attempts, the watcher transitions to `failed` and emits `kind:"error"`.

Reconnect listener:

```ts
scheduleReconnect: async ({ countAttempt = true }) => {
  if (values.failed || isTerminalStatus(values.lastStatus)) return
  if (countAttempt) actions.incrementReconnectAttempt()
  else actions.resetReconnectAttempts()
  if (values.reconnectAttempts > MAX_SSE_RECONNECT_ATTEMPTS) {
    actions.failWatcher({ title: 'Cloud stream disconnected', ... })
    return
  }
  const delay = Math.min(
    SSE_RECONNECT_BASE_DELAY_MS * 2 ** Math.max(values.reconnectAttempts - 1, 0),
    SSE_RECONNECT_MAX_DELAY_MS,
  )
  cache.disposables.add(
    () => {
      const id = setTimeout(() => actions.connectSse({ startLatest: !values.lastEventId }), delay)
      return () => clearTimeout(id)
    },
    `reconnect-${values.reconnectAttempts}`,
  )
}
```

Use `cache.disposables.add(...)` rather than ad-hoc `setTimeout` with manual `clearTimeout` in `beforeUnmount`. The kea-disposables plugin (`frontend/src/kea-disposables.ts`) auto-cleans on unmount and pauses on hidden tabs — exactly what we want for a reconnect timer.

### 5.5 Reference counting (multi-mount safety)

`maxThreadLogic` today is mounted by `BindLogic` from `Max.tsx`. When the user opens the same chat in two browser tabs, two `maxThreadLogic` instances mount (keyed by `${conversationId}-${tabId}`). Today each instance opens its own SSE — fine for a single endpoint, but wasteful for the cloud-agent stream.

The desktop `CloudTaskService.watch` (`service.ts:222-237`) uses **process-wide reference counting** — there's only ever one SSE per `(taskId, runId)` across all renderer windows. We reproduce this in-browser by sharing the keyed `runWatcherLogic` instance: Kea's keyed logic creates one logic per key, regardless of how many React subtrees mount it.

The `subscribe` / `unsubscribe` actions are NOT user-driven — they're triggered by `posthogAiThreadLogic.afterMount` and `beforeUnmount` respectively:

```ts
// In posthogAiThreadLogic
connect: ({ taskId, currentRunId }) => ({
  values: [
    runWatcherLogic({ taskId, runId: currentRunId! }),
    ['latestUpdate', 'permissionRequest', 'lastStatus', 'isBootstrapping', 'connectionError'],
  ],
}),

afterMount: ({ actions, values, cache }) => {
  if (values.currentRunId) {
    const watcher = runWatcherLogic({ taskId: values.task!.id, runId: values.currentRunId })
    cache.watcherUnmount = watcher.mount()
    watcher.actions.subscribe()
  }
}

beforeUnmount: ({ values, cache }) => {
  if (values.currentRunId) {
    runWatcherLogic({ taskId: values.task!.id, runId: values.currentRunId }).actions.unsubscribe()
    cache.watcherUnmount?.()
  }
}
```

Inside `runWatcherLogic`:

```ts
listeners(({ actions, values }) => ({
  subscribe: () => {
    // On the very first subscriber, kick off bootstrap.
    if (values.subscriberCount === 1 && !values.hasEmittedSnapshot && !values.isBootstrapping) {
      actions.startBootstrap()
      return
    }
    // Subsequent subscribers get a re-emit of the current snapshot, just like
    // desktop's emitCurrentSnapshot (service.ts:885-925) — they need to receive
    // the historical log entries to render anything.
    if (values.hasEmittedSnapshot) {
      actions.replaySnapshotForSubscriber()
    }
  },
  unsubscribe: () => {
    if (values.subscriberCount === 0) {
      actions.stopWatcher()
    }
  },
}))
```

`replaySnapshotForSubscriber` calls `fetchAllSessionLogs` again and merges with `emittedLogEntries` to produce a fresh `kind:"snapshot"` (port of `mergeHistoricalAndEmittedEntries`, `service.ts:848-883`). This is the cost of refusing to keep an in-memory thread copy at the watcher level — every new subscriber pays one network round-trip on join. Acceptable since this is exceptional (sidepanel + scene + history-preview-with-thread-summary all wanting the same stream).

### 5.6 Connection error ladder

Direct port of `createStreamStatusError` (`service.ts:144-204`, Twig § 5.6). Map to user-facing copy and the retry affordance:

| HTTP | `title` | `message` | `retryable` | `autoRetry` |
|---|---|---|---|---|
| 401 | "Authentication expired" | "Please reauthenticate and reload the chat." | `true` | `false` |
| 403 | "Access denied" | "You no longer have access to this chat. Reauthenticate and retry." | `true` | `false` |
| 404 | "Chat not found" | "This chat could not be found. It may have been deleted." | `false` | `false` |
| 406 | "Stream unavailable" | "The backend rejected the live stream request. Retry shortly." | `true` | `false` |
| other | "Stream failed" | "The chat stream request failed with status {status}. Retry to reconnect." | `true` | `true` |

`autoRetry: false` surfaces a "Retry" button in the SessionView-equivalent error overlay (§ 9.2) instead of looping silently.

`shouldFailWatcherForFetchStatus` (`service.ts:207-209`): on initial REST `GET /runs/{rid}/`, 401/403/404 should fail non-retryably without ever opening SSE.

---

## 6. Sending messages

### 6.1 First message (new Task)

Sequence (orchestrated by `posthogAiThreadLogic.askPostHogAi`):

1. Take `prompt: string` and currently-compiled UI context (see `01_CONTEXT.md` for compilation).
2. Optimistically push a `user_message` `ThreadMessage` to local state. Set `frontendTaskId` as the temporary key.
3. `POST /api/projects/{tid}/tasks/` with `{ title: prompt.slice(0, 80), description: prompt, origin_product: "posthog_ai", repository: null, github_integration: null, github_user_integration: null }`. Returns `Task` with `id`.
4. Replace URL `?chat=<frontendTaskId>` with `?chat=<task.id>` via `actionToUrl` `{ replace: true }`.
5. `POST /api/projects/{tid}/tasks/{task.id}/run/` with body:

   ```ts
   {
     mode: "interactive",
     // No environment — defaults to "cloud" for /run/ (Twig § 4.2 vs § 4.3).
     pending_user_message: prompt,                            // also valid: serializeCloudPrompt([...])
     pending_user_artifact_ids: [],                           // PostHog AI has no attachments today (see § 6 note)
     initial_permission_mode: defaultPermissionMode(),        // see § 6.7
     run_source: "manual",
     // Adapter / model / reasoning are left to the backend default for now.
     // Bake user-specific overrides into the systemPrompt server-side (04_PROMPTS.md).
   }
   ```

6. The response is `Task` with `latest_run` populated. Extract `latest_run.id` as `currentRunId`.
7. Mount `runWatcherLogic({ taskId: task.id, runId: currentRunId })` (§ 5.5).
8. Emit telemetry `PROMPT_SENT` with `{ is_initial: true, prompt_length_chars, execution_type: "cloud", task_id }`.

`mode: "interactive"` vs `"background"`: PostHog AI is always interactive — the user is sitting in the UI waiting for a reply. `"background"` is for Code's "run this overnight" path. For our resume flow (§ 6.5) we also use `"interactive"`.

**No attachments today.** PostHog AI doesn't accept file uploads in the chat input. The Task model still allows it via `pending_user_artifact_ids` and `staged_artifacts/prepare_upload/`, but we pass `[]`. If we ever add attachments, port `uploadTaskStagedAttachments` and `uploadRunAttachments` from `Twig/apps/code/src/renderer/features/sessions/utils/cloudArtifacts.ts`.

**No `serializeCloudPrompt` indirection for the simple case.** Per Twig § 7, a single-text-block prompt round-trips as a plain string. We send the plain string and let the agent-server normalize on read. The `__twig_cloud_prompt_v1__:` prefix only matters when we have multi-block content (which we don't, yet).

### 6.2 Follow-up while in-progress (POST /command/ user_message)

Sequence (orchestrated by `sendFollowUp` in `posthogAiThreadLogic`):

```ts
sendFollowUp: async ({ prompt }) => {
  const { taskId, currentRunId, isPromptPending, lastStatus } = values
  if (!currentRunId || lastStatus !== 'in_progress' || isPromptPending) {
    return actions.enqueueQueuedMessage(prompt)                       // see § 6.3
  }
  // Optimistic push.
  actions.appendMessage({ type: 'user_message', content: prompt, status: 'completed' })
  actions.setIsPromptPending(true)

  try {
    const result = await runWatcherLogic({ taskId, runId: currentRunId }).asyncActions.sendCommand({
      method: 'user_message',
      params: { content: prompt },
    })
    if (result.error) throw new Error(result.error)
    // result.result.stopReason ∈ { "end_turn", "queued", ... }. We don't gate on it;
    // the watcher will emit `_posthog/turn_complete` when the run actually ends.
  } catch (e) {
    actions.setIsPromptPending(false)
    // Roll back the optimistic message.
    actions.removeLastOptimisticMessage()
    lemonToast.error(parseApiError(e))
  }
}
```

`sendCommand` inside `runWatcherLogic` is a thin wrapper around `POST /api/projects/{tid}/tasks/{tid}/runs/{rid}/command/` (Twig § 6). The JSON-RPC envelope (`jsonrpc: "2.0"`, `method`, `params`, `id`) is constructed inside the watcher.

### 6.3 Follow-up while queued / sandbox not ready (client-side queue)

If `lastStatus` is `"queued"` (sandbox provisioning), or `"in_progress"` but we haven't yet observed `_posthog/run_started` (i.e. ACP session not initialized — the equivalent of desktop's `session.status !== "connected"` from Twig § 13.11), or there's already a `user_message` in flight (`isPromptPending`), we **enqueue locally**. Server-side queue endpoint is gone.

The `_posthog/run_started` notification flips an `isAgentReady` selector in `runWatcherLogic`:

```ts
selectors({
  isAgentReady: [
    (s) => [s.emittedLogEntries],
    (entries) => entries.some(e =>
      e.notification?.method === '_posthog/run_started'
      || e.notification?.method === 'posthog/run_started'
    ),
  ],
})
```

(Twig § 10.5 step 12 emits `_posthog/run_started`; § 10.8 documents the namespace tolerance.)

Queue model:

```ts
interface QueuedPrompt {
  id: string                        // local uuid
  content: string                   // plain text
  rawPrompt?: ContentBlock[]        // present only if attachments are added later
  enqueuedAt: number
}

reducers({
  queuedMessages: [[] as QueuedPrompt[], {
    enqueueQueuedMessage: (state, { prompt }) => [...state, { id: uuid(), content: prompt, enqueuedAt: Date.now() }],
    removeQueuedMessage: (state, { id }) => state.filter(q => q.id !== id),
    clearQueuedMessages: () => [],
    drainQueuedMessages: () => [],
  }],
})
```

The queue is **per-Task, per-tab**. Cross-tab queue sync is intentionally NOT done — too much complexity for low value. If a user enqueues in tab A and switches to tab B before the agent is ready, the queue stays in tab A. (If we ever need this, pipe through `tabAwareScene` cache or BroadcastChannel.)

### 6.4 Combining queued prompts (combineQueuedCloudPrompts equivalent)

When the agent becomes ready (`_posthog/run_started` arrives) or finishes a turn (`_posthog/turn_complete`), drain the queue and merge:

```ts
listeners(({ actions, values }) => ({
  // Subscribe to runWatcherLogic's latestUpdate; on a turn_complete or run_started entry,
  // attempt to consume the queue.
  applyWatcherUpdate: ({ update }) => {
    if (update.kind === 'logs') {
      const sawTurnComplete = update.newEntries.some(e =>
        e.notification?.method === '_posthog/turn_complete'
        || e.notification?.method === 'posthog/turn_complete'
      )
      const sawRunStarted = update.newEntries.some(e =>
        e.notification?.method === '_posthog/run_started'
        || e.notification?.method === 'posthog/run_started'
      )
      if (sawTurnComplete || sawRunStarted) {
        actions.consumeQueuedMessages()
      }
    }
  },
  consumeQueuedMessages: async () => {
    if (cache.consumingQueue) return                  // re-entrance guard
    cache.consumingQueue = true
    try {
      if (values.queuedMessages.length === 0) return
      if (values.isPromptPending) return
      if (values.lastStatus !== 'in_progress') return
      if (!values.isAgentReady) return

      const drained = values.queuedMessages
      actions.drainQueuedMessages()
      const combined = combineQueuedPrompts(drained)    // see below
      if (!combined) return
      await actions.sendFollowUp(combined)              // skip queue guard
    } catch (err) {
      // Restore the queue on failure so the next trigger retries.
      actions.restoreQueuedMessages(drained)
    } finally {
      cache.consumingQueue = false
    }
  },
}))
```

`combineQueuedPrompts` is the in-browser port of `combineQueuedCloudPrompts` (`Twig/apps/code/src/renderer/features/sessions/utils/cloudArtifacts.ts:392-417`). For the no-attachments PostHog AI case it simplifies to joining content with `"\n\n"`:

```ts
function combineQueuedPrompts(prompts: QueuedPrompt[]): string | null {
  if (prompts.length === 0) return null
  return prompts.map(p => p.content.trim()).filter(Boolean).join('\n\n')
}
```

When we add attachments, this needs to grow to handle `ContentBlock[]` and produce the `__twig_cloud_prompt_v1__:` envelope per Twig § 7.

**Re-entrance guard**: same as desktop (`service.ts:1851-1892`, the `dispatchingCloudQueues` set). The `cache.consumingQueue` flag prevents double-dispatch when both `run_started` and `turn_complete` arrive in the same batch.

### 6.5 Resume after terminal (POST /tasks/{id}/run/ with resume_from_run_id)

Triggered when the user sends a message AND `values.lastStatus` is terminal (`completed`/`failed`/`cancelled`):

```ts
askPostHogAi: async ({ prompt }) => {
  if (!values.currentRunId) {
    return actions.startNewChat(prompt)                  // First message ever — § 6.1
  }
  if (isTerminalStatus(values.lastStatus)) {
    return actions.resumeAfterTerminal(prompt)
  }
  return actions.sendFollowUp(prompt)
}

resumeAfterTerminal: async ({ prompt }) => {
  const { task, currentRunId } = values

  // Pull the prior Run for state propagation. Cheap — already in memory if the watcher is mounted.
  const previousRun = await api.tasks.getRun(task.id, currentRunId)

  // Optional safety net for "failed before even booting":
  if (previousRun.status === 'failed' && !values.isAgentReady) {
    lemonToast.error(
      values.lastErrorMessage
      || "PostHog AI couldn't start. Please try a new chat."
    )
    return
  }

  // Optimistic message.
  actions.appendMessage({ type: 'user_message', content: prompt, status: 'completed' })

  const newTask = await api.tasks.runInCloud(task.id, {
    mode: 'interactive',
    pending_user_message: prompt,
    pending_user_artifact_ids: [],
    resume_from_run_id: currentRunId,
    run_source: previousRun.state?.run_source ?? 'manual',
    signal_report_id: previousRun.state?.signal_report_id,
    initial_permission_mode: previousRun.state?.initial_permission_mode ?? defaultPermissionMode(),
    // Carry over per-Run runtime config from previousRun.
    runtime_adapter: previousRun.runtime_adapter ?? undefined,
    model: previousRun.model ?? undefined,
    reasoning_effort: previousRun.reasoning_effort ?? undefined,
  })

  const newRunId = newTask.latest_run!.id

  // Unmount the old watcher, mount the new one.
  runWatcherLogic({ taskId: task.id, runId: currentRunId }).actions.unsubscribe()
  actions.setCurrentRunId(newRunId)
  runWatcherLogic({ taskId: task.id, runId: newRunId }).mount()
  runWatcherLogic({ taskId: task.id, runId: newRunId }).actions.subscribe()
}
```

The thread visibly continues. The agent-server's `resumeFromLog` (Twig § 10.6 step 1) replays the prior conversation transcript into the new ACP session.

### 6.6 Cancel

```
runWatcherLogic.actions.sendCommand({ method: 'cancel', params: {} })
```

Server returns `{ cancelled: true }` (Twig § 6.3). The watcher will then receive a `task_run_state` event with `status: "cancelled"` and emit it. Local state changes:

```ts
listeners({
  cancelRun: async () => {
    if (values.cancelLoading) return
    actions.setCancelLoading(true)
    try {
      const result = await runWatcherLogic({ taskId: values.task!.id, runId: values.currentRunId! })
        .asyncActions.sendCommand({ method: 'cancel', params: {} })
      if (!result.success) throw new Error(result.error)
      actions.clearQueuedMessages()
      track('TASK_RUN_CANCELLED', { execution_type: 'cloud', task_id: values.task!.id })
    } catch (e) {
      lemonToast.error(parseApiError(e))
    } finally {
      actions.setCancelLoading(false)
    }
  }
})
```

### 6.7 Permission response

`permission_request` SSE events come through `runWatcherLogic` as `CloudTaskPermissionRequestUpdate` (Twig § 2.8, § 5.3). The thread logic surfaces this verbatim as `pendingPermissionRequest`:

```ts
reducers({
  pendingPermissionRequest: [null as CloudTaskPermissionRequestUpdate | null, {
    applyWatcherUpdate: (state, { update }) =>
      update.kind === 'permission_request' ? update : state,
    respondToPermission: () => null,                     // optimistic clear
  }],
})

listeners({
  respondToPermission: async ({ requestId, optionId, customInput }) => {
    try {
      await runWatcherLogic({ taskId: values.task!.id, runId: values.currentRunId! })
        .asyncActions.sendCommand({
          method: 'permission_response',
          params: { requestId, optionId, customInput },
        })
      track('PERMISSION_RESPONDED', { option_id: optionId, task_id: values.task!.id })
    } catch (e) {
      // Re-instate the permission_request on failure.
      lemonToast.error(parseApiError(e))
    }
  }
})
```

The `DangerousOperationApprovalCard` component (today's `frontend/src/scenes/max/DangerousOperationApprovalCard.tsx`) is **kept** but rewired: it consumes `pendingPermissionRequest` instead of `pendingApprovalsData[proposalId]`. The wire-level translation lives in `03_RICH_UI.md`; from this spec's standpoint, all we owe is the `pendingPermissionRequest` and the `respondToPermission` action.

**Cancel-with-feedback**: `optionId: "reject_with_feedback"`, `customInput: "User cancelled the permission request."` — same convention as desktop (Twig § 6.5, § 13.14).

**Default permission mode** (§ 9 open question): the recommendation is **`acceptEdits`** for PostHog AI. Reasoning: most PostHog AI actions are read-only (HogQL queries, taxonomy lookups), so `acceptEdits` produces no friction for those. Writes (creating notebooks, dashboards) DO get a confirmation — matching today's `DangerousOperationApprovalCard` flow. `bypassPermissions` removes the safety net for writes; `default` produces friction even for reads.

```ts
function defaultPermissionMode(): PermissionMode {
  return 'acceptEdits'
}
```

This is sent as `state.initial_permission_mode` at Run creation. The server picks it up at `agent-server.ts:940-945`.

---

## 7. Thread message model

This section is where PostHog AI's "today" diverges most sharply from the cloud-agent world. Today the thread is a list of `RootAssistantMessage` objects (`AssistantMessage`, `HumanMessage`, `AssistantToolCallMessage`, `FailureMessage`, …). Tomorrow the thread is **derived from a stream of ACP `session/update` events**, which look very different.

### 7.1 ACP `session/update` events → message reducer

The `StoredLogEntry`s that the watcher emits (Twig § 2.8, § 10.9) carry an embedded JSON-RPC notification. Relevant `sessionUpdate` kinds for thread folding:

- `agent_message_chunk` — `{ content: { type: "text", text: <chunk> } }`. Streaming token output.
- `agent_message` — `{ content: { type: "text", text: <full_message> } }`. The coalesced final message (Twig § 10.10).
- `tool_call` — `{ toolCallId, title, kind, content, rawInput }`. A tool was invoked.
- `tool_call_update` — incremental updates to an in-flight tool call (status flips, content additions).
- `current_mode_update` — `{ currentModeId }`. Agent switched mode (e.g., into `plan` mode).

Other notifications we observe but don't fold into the thread directly:

- `_posthog/run_started` — flips `isAgentReady` (§ 6.3).
- `_posthog/turn_complete` — drains queue (§ 6.4).
- `_posthog/error` — surfaces in `errorOverlay`.
- `_posthog/progress` — drives the "Pondering…" thinking message (Overview, Surfaces preserved table).
- `_posthog/usage_update` — feeds `/usage` slash command (§ 8.3).

The folding logic lives as a selector in `posthogAiThreadLogic`:

```ts
selectors({
  messages: [
    (s) => [s.task, s.runEmittedEntries, s.optimisticMessages],
    (task, entries, optimistic): ThreadMessage[] => foldEntriesToMessages(entries, optimistic, task),
  ],
})
```

`runEmittedEntries` is the merged historical-log + live-SSE stream from `runWatcherLogic`. `foldEntriesToMessages` walks the stream and produces:

```ts
type ThreadMessageType = 'user_message' | 'assistant_message' | 'tool_call' | 'permission_request' | 'failure'

interface ThreadMessage {
  id: string                                // log entry id or tool_call_id
  type: ThreadMessageType
  status: 'streaming' | 'completed' | 'failed'
  // Per-type fields:
  content?: string                          // user_message, assistant_message
  toolCallId?: string
  toolKind?: string                         // tool_call: "read", "edit", "write", "switch_mode", "question", or a custom MCP tool name
  toolTitle?: string
  toolContent?: unknown[]                   // forwarded to renderers in 03_RICH_UI
  toolStatus?: 'in_progress' | 'completed' | 'failed'
  permissionRequestId?: string              // permission_request: for the approval card
  errorMessage?: string                     // failure
  traceId?: string                          // taskRunId (see § 9.3)
  timestamp?: string
}
```

The fold pseudocode:

```ts
function foldEntriesToMessages(
  entries: StoredLogEntry[],
  optimistic: ThreadMessage[],
  task: Task | null,
): ThreadMessage[] {
  const result: ThreadMessage[] = []
  let pendingAgentChunk: { id: string; text: string } | null = null

  for (const entry of entries) {
    const n = entry.notification
    if (!n) continue

    if (n.method === 'session/update') {
      const update = n.params?.update as any
      switch (update?.sessionUpdate) {
        case 'agent_message_chunk':
          if (!pendingAgentChunk) {
            pendingAgentChunk = { id: `chunk-${entry.timestamp}`, text: '' }
            result.push({
              id: pendingAgentChunk.id,
              type: 'assistant_message',
              status: 'streaming',
              content: '',
              timestamp: entry.timestamp,
            })
          }
          pendingAgentChunk.text += update.content?.text ?? ''
          result[result.length - 1] = {
            ...result[result.length - 1],
            content: pendingAgentChunk.text,
          }
          break

        case 'agent_message':
          // Coalesced final form — replaces in-flight chunks at the same position.
          if (pendingAgentChunk) {
            result[result.length - 1] = {
              ...result[result.length - 1],
              status: 'completed',
              content: update.content?.text ?? pendingAgentChunk.text,
            }
            pendingAgentChunk = null
          } else {
            result.push({
              id: `msg-${entry.timestamp}`,
              type: 'assistant_message',
              status: 'completed',
              content: update.content?.text ?? '',
              timestamp: entry.timestamp,
            })
          }
          break

        case 'tool_call':
          result.push({
            id: update.toolCallId,
            type: 'tool_call',
            status: 'streaming',
            toolCallId: update.toolCallId,
            toolKind: update.kind,
            toolTitle: update.title,
            toolContent: update.content,
            toolStatus: 'in_progress',
            timestamp: entry.timestamp,
          })
          break

        case 'tool_call_update':
          // Find the existing tool_call by toolCallId and patch it in place.
          const idx = result.findIndex(m => m.id === update.toolCallId)
          if (idx !== -1) {
            result[idx] = {
              ...result[idx],
              toolContent: [
                ...(result[idx].toolContent ?? []),
                ...(update.content ?? []),
              ],
              toolStatus: update.status ?? result[idx].toolStatus,
              status: update.status === 'completed' || update.status === 'failed' ? 'completed' : 'streaming',
            }
          }
          break

        case 'current_mode_update':
          // Surface as a "mode switch" pill, not a fully-fledged message.
          // For now: ignore in the thread; expose via `currentMode` selector.
          break
      }
    } else if (n.method === '_posthog/user_message' || n.method === 'posthog/user_message') {
      // The agent-server echoes user messages back into the log on relay.
      result.push({
        id: `user-${entry.timestamp}`,
        type: 'user_message',
        status: 'completed',
        content: extractTextFromUserMessage(n.params),
        timestamp: entry.timestamp,
      })
    } else if (n.method === '_posthog/error' || n.method === 'posthog/error') {
      result.push({
        id: `err-${entry.timestamp}`,
        type: 'failure',
        status: 'failed',
        errorMessage: n.params?.message ?? 'Agent error',
        timestamp: entry.timestamp,
      })
    }
  }

  // Merge optimistic user messages that haven't been echoed yet.
  for (const opt of optimistic) {
    const echoed = result.some(m =>
      m.type === 'user_message' && m.content === opt.content
    )
    if (!echoed) result.push(opt)
  }

  return result
}
```

### 7.2 Coalescing agent_message_chunk

The agent-server's `SessionLogWriter` already coalesces consecutive `agent_message_chunk` into one `agent_message` (Twig § 10.10, `session-log-writer.ts:112-160`). So for **historical** entries we mostly see fully-coalesced `agent_message` notifications. For **live** streaming, both chunks and the final `agent_message` arrive in sequence — the fold logic above handles both cases.

There's a subtle case where the SSE stream emits an `agent_message_chunk` AFTER the persisted log has been coalesced into an `agent_message` (e.g., on bootstrap reconnect with `Last-Event-ID`). The content-dedup in § 5.3 should catch this — the chunk's serialized JSON differs from the message's serialized JSON, so it won't be deduped, and we'd append a duplicate. This is acceptable because:

(a) `SessionLogWriter` flushes every 500ms — chunk-after-coalesced is rare in practice.
(b) The fold logic checks `pendingAgentChunk`; if we already have a completed `agent_message` and then see another chunk for the same logical position, we'd start a new streaming message — visible as a glitch but recoverable.

If this becomes a real issue, add a "last completed `agent_message` start-of-content" check in the fold.

### 7.3 Tool call placeholders (rendered by 03)

A `tool_call` ThreadMessage becomes a placeholder in the thread. The actual rendering (which calls into `messages/VisualizationArtifactAnswer.tsx`, `NotebookArtifactAnswer.tsx`, `UIPayloadAnswer.tsx`, etc.) lives in `03_RICH_UI.md`. From this spec's view, we just need to ensure:

- The `tool_call` ThreadMessage carries enough fields (`toolCallId`, `toolKind`, `toolTitle`, `toolContent`, `toolStatus`) for the renderer dispatcher to switch on.
- A `tool_call_update` mutates the existing entry in place rather than appending — the renderer can re-render efficiently.
- A `tool_call` with `kind === "switch_mode"` is special — it's a plan-mode approval and routes through the permission_request flow, not a normal tool-call render. The folder leaves it as a normal `tool_call` ThreadMessage; the renderer can check `toolKind === "switch_mode"` and render appropriately, or `03_RICH_UI.md` can add a separate `mode_switch_request` ThreadMessage type.

### 7.4 Approval pending state

`pendingPermissionRequest` is a separate selector, not folded into `messages[]`. Reason: the approval is a transient UI affordance attached to the bottom of the thread, not a chat message. The `permission_request` SSE event arrives alongside the relevant `tool_call` — we render the approval card next to (or below) the tool_call placeholder.

```ts
selectors({
  pendingPermissionRequest: [
    (s) => [s.runPermissionRequest, s.respondedRequestIds],
    (req, responded) => req && !responded.has(req.requestId) ? req : null,
  ],
})

reducers({
  respondedRequestIds: [new Set<string>(), {
    respondToPermission: (state, { requestId }) => new Set([...state, requestId]),
  }],
})
```

When the user resolves an approval, we optimistically add to `respondedRequestIds` and dispatch the `permission_response` command. If the command fails, we'd need a rollback action — for now we just toast the error and let the next `permission_request` arrive (the agent-server would re-emit since it never received a response).

### 7.5 Optimistic user-message append

On `sendFollowUp` / first-message / resume, we push an optimistic `user_message` ThreadMessage to a separate `optimisticMessages` reducer. The fold merges with the watcher stream, deduping by content match (§ 7.1 last paragraph).

When the agent-server logs a `_posthog/user_message` notification (Twig § 10.8), the echoed message wins (it has a real `timestamp`); the optimistic version is dropped from the merge.

**Trace-id matching**: today's Max uses `trace_id` to match a streamed Human message against the optimistic one (`maxThreadLogic.tsx:2019-2043`). In the new world we don't have a per-message trace id; matching on `content` is enough since the user can't send two identical messages in a row faster than the echo round-trip.

### 7.6 Failure / retry surface

A `failure` ThreadMessage from `_posthog/error` shows inline at the bottom. Beyond that, the **connection-level error overlay** (§ 9.2) shows when `runWatcherLogic.connectionError` is set — this is for transport failures, not agent failures. The two are distinct and both should be visible.

Retry: for a `failure` ThreadMessage (agent error), the user retries by sending a new message — which resumes if the run is terminal, follows-up if not. There's no explicit "retry" affordance for individual messages.

For connection errors, the overlay shows a "Retry" button that calls `runWatcherLogic.actions.retry()`.

---

## 8. Slash commands — disposition matrix

Today's commands (`frontend/src/scenes/max/slash-commands.tsx`):

```
SlashInit       — Set up knowledge about your product & business
SlashRemember   — Add [information] to PostHog AI's project-level memory
SlashUsage      — View AI credit usage for this conversation
SlashFeedback   — Share feedback about your PostHog AI experience
SlashTicket     — Create a support ticket with a summary of this conversation
```

Each command needs to land in one of three buckets:

1. **Browser-handled** — never hits the agent. UI-only side effect (open a modal, copy to clipboard).
2. **`user_message` with backend pre-processing** — the command becomes part of the user's message; the backend's `build_posthog_ai_system_prompt` (see `04_PROMPTS.md`) intercepts and rewrites before sending to the agent.
3. **MCP tool invocation** — the command directly invokes an MCP tool (typically `posthog-memory` or `posthog-context`) without going through the agent's natural-language layer.

### 8.1 /init

**Disposition**: `user_message` with backend pre-processing.

Today's `/init` triggers a `slash_command_init` flow in `ee/hogai/chat_agent` that probes for product memory, event taxonomy, etc., then writes `Core memory`. The agent intelligence is real — we want the model to use its tools to investigate.

In the new world: `/init` becomes a `user_message` with a canned content rewrite. The browser sends `content: "Please run the initialization sequence for this project."`; the backend's system-prompt builder detects the chat is a fresh Task whose `description` starts with that exact string and prepends an instructional block (`04_PROMPTS.md` § 3).

Browser side: when the user activates `/init`, `posthogAiThreadLogic` calls `askPostHogAi("Please run the initialization sequence for this project.")` — no special UI handling.

### 8.2 /remember

**Disposition**: MCP tool invocation (preferred) **OR** `user_message` with pre-processing (fallback).

`/remember [information]` is a write to the project's core memory. Two paths:

- **Preferred**: a `posthog-memory` MCP server exposes a `remember` tool. The agent-server has it auto-registered. The browser dispatches via `sendCommand({ method: "user_message", params: { content: "/remember <text>" } })`; the system prompt instructs the agent to interpret leading `/remember` as a direct call to `remember(text)`. The agent skips natural-language reasoning for this case.
- **Fallback** (if MCP isn't ready in Phase 1): browser detects `/remember` prefix and calls a direct REST endpoint `POST /api/projects/{tid}/posthog_ai_memory/` with `{ text }`. The chat shows "Remembered: <text>" inline as a synthesized assistant message (no agent involvement). This was the original behavior in earlier Max iterations.

Recommendation: go with the MCP path. It's the spirit of the migration and keeps the memory writable from any client (including non-PostHog-UI tools).

### 8.3 /usage

**Disposition**: browser-handled.

`/usage` shows AI credit usage for the current conversation. The data source: the agent-server emits `_posthog/usage_update` notifications (Twig § 10.8) with cumulative token counts and cost estimates. We surface them in the thread logic:

```ts
selectors({
  usageStats: [
    (s) => [s.runEmittedEntries],
    (entries) => {
      const usage = entries
        .filter(e => e.notification?.method === '_posthog/usage_update' || e.notification?.method === 'posthog/usage_update')
        .map(e => e.notification!.params)
      return aggregateUsage(usage)
    },
  ],
})

listeners({
  activateCommand: ({ command }) => {
    if (command.name === SlashCommandName.SlashUsage) {
      actions.appendMessage({
        id: `usage-${Date.now()}`,
        type: 'assistant_message',
        status: 'completed',
        content: formatUsage(values.usageStats),
      })
      actions.setQuestion('')
      return
    }
    // ... other commands
  }
})
```

No round-trip to the agent. Pure UI affordance.

### 8.4 /feedback

**Disposition**: browser-handled.

`/feedback` opens the existing `FeedbackPrompt.tsx` UI (preserved as-is per Overview § 4). The slash-command listener just shows the feedback modal — no agent involvement.

### 8.5 /ticket

**Disposition**: browser-handled (today's behavior preserved).

`/ticket` already runs entirely on the frontend via `TicketPrompt.tsx` + `ticketUtils.ts`. It composes a conversation summary (`thread.map(m => m.content).join("\n\n")`) and pre-fills a support ticket form. Nothing changes here — except `requiresIdle: true` becomes `lastStatus !== 'in_progress'` in our new model.

Summary disposition table:

| Command | Disposition | Notes |
|---|---|---|
| `/init` | `user_message` + backend prompt rewrite | Phase 1 needs the rewrite path in `04_PROMPTS.md` |
| `/remember` | MCP tool invocation | Fallback: REST `posthog_ai_memory/`; rewrite the assistant reply locally |
| `/usage` | Browser-handled | Aggregates `_posthog/usage_update` notifications from the log |
| `/feedback` | Browser-handled | Opens existing FeedbackPrompt; unchanged |
| `/ticket` | Browser-handled | Summarizes thread; unchanged. `requiresIdle` now means `lastStatus !== 'in_progress'` |

---

## 9. UX & state

### 9.1 Initializing screen (CloudInitializingView equivalent)

Port `Twig/apps/code/src/renderer/features/sessions/components/CloudInitializingView.tsx` to `frontend/src/scenes/posthog-ai/components/PostHogAiInitializingView.tsx`. The structural rules from Twig § 13.9:

- 2-second delay before any content (avoid flicker on fast bootstraps). Implemented via a `setTimeout` inside the component, gated by `cache.disposables.add` semantics so it doesn't fire after unmount.
- After 2s, show a centered illustration + copy varying by `cloudStatus`:
  - `"queued"` → "Reserving compute…" / "Spinning up Max — this can take a few seconds."
  - `"in_progress"` (but no `_posthog/run_started` yet) → "Starting up…" / "Connecting to your PostHog AI runner."
  - Otherwise → "Getting things ready…" / "Connecting…"

`isInitializing` selector (mirror of Twig § 13.9's predicate):

```ts
isInitializing: [
  (s) => [s.task, s.lastStatus, s.isAgentReady, s.connectionError, s.messages],
  (task, lastStatus, isAgentReady, connectionError, messages): boolean => {
    if (connectionError) return false                          // overlay takes over
    if (!task || !lastStatus) return true
    const isNonTerminal = !['completed', 'failed', 'cancelled'].includes(lastStatus)
    return isNonTerminal && (!isAgentReady || messages.length === 0)
  },
]
```

Note: we keep this gated to the **first turn** only. Subsequent turns in the same chat don't show the initializing view, even if there's a brief gap between `user_message` and `agent_message_chunk` — for that, the `currentThinkingMessage` (today's thinking-messages.ts) covers the in-turn wait.

### 9.2 Error overlay

Mirror of Twig § 13.10 `SessionView` error overlay. When `runWatcherLogic.connectionError` is set:

- Red bold title (`error.title`).
- Body (`error.message`).
- "Retry" button: `runWatcherLogic.actions.retry()`. Hidden if `!error.retryable`.
- "Start new chat" link: `posthogAiLogic.actions.startNewChat()`. Shown if `!error.retryable` (i.e., 404 — the chat doesn't exist anymore).

The overlay sits above the thread (covers the input). The thread itself remains visible behind it (translucent backdrop) so the user can see what they were doing.

Special case: if `lastStatus === 'failed'` AND we never received `_posthog/run_started`, the failure is at the sandbox-provisioning level — the agent never booted. Show a more specific message: "PostHog AI couldn't start. Please try a new chat." (Per Twig § 13.11 line 1685-1689.)

### 9.3 Trace ID

Today: client-generates per-turn `traceId = uuid()` (`maxThreadLogic.tsx:615-624`).

New world recommendation: **use `runId` as the trace id, and emit a synthetic `_posthog/run_started` body field `trace_id: <runId>` for parity with the LLM Analytics dashboards.**

Rationale: a `Run` is exactly one user-turn-to-terminal sequence. Within a single Run, the agent may make many ACP `prompt()` calls (each user follow-up via `POST /command/` triggers another `prompt`). Today's `trace_id` rolls each of those as a separate trace. To preserve that behavior, we need finer granularity than `runId`.

Two options:

- (a) Use `runId` as `trace_id` for the whole chat session. Loses per-turn granularity but is simplest.
- (b) Generate `trace_id = uuid()` per `sendFollowUp` / `askPostHogAi` invocation, pass through as `_meta.trace_id` on the `user_message` command's `params`. The agent-server forwards into ACP `_meta`, the relay stores in the log, LLM Analytics indexes from there.

Recommendation: **(b)**, with `trace_id` stored on every assistant message (`AssistantMessage.trace_id`). The `runId` lives alongside as `task_run_id` for the chat-level join key. This preserves today's analytics surface.

The `posthogAiThreadLogic.traceId` selector returns the most-recent `trace_id` from the last user message — what the UI displays for the "report this conversation" button.

### 9.4 Telemetry parity

Keep parity with today's `posthog.capture(...)` events. Translation table:

| Today | Tomorrow | Properties |
|---|---|---|
| `max conversation turn completed` (`maxThreadLogic.tsx:802-813`) | Keep the same event name. | `conversation_id` → `task_id`, add `task_run_id`, keep `trace_id`, keep `status` (`success | failure | cancelled | generation_error`), drop `agent_mode` (or rename to `permission_mode`), keep `generation_attempt` |
| `PROMPT_SENT` (desktop, Twig § 16) | Add. | `task_id`, `execution_type: "posthog_ai_cloud"`, `is_initial`, `prompt_length_chars` |
| `TASK_RUN_CANCELLED` (Twig § 16) | Add. | `task_id`, `execution_type: "posthog_ai_cloud"` |
| `PERMISSION_RESPONDED` | Add. | `task_id`, `option_id`, `tool_kind` |
| `TASK_VIEWED` | Convert from today's "chat opened" telemetry. | `task_id` |

The `posthog.capture('max…')` event names are preserved (don't break dashboards). The `conversation_id` property is the legacy name we keep populating with `task_id`. New properties (`task_run_id`, `permission_mode`) are additive.

---

## 10. Tab-aware scene integration

Today's `Max.tsx` uses `tabAwareScene()` on `maxLogic` (`maxLogic.tsx:140`) plus `tabAwareUrlToAction` / `tabAwareActionToUrl`. We do the same on `posthogAiLogic`.

URL routing changes from `/ai` to `/posthog-ai` (chosen to avoid clashing with any existing `/ai` routes). Update `frontend/src/scenes/urls.ts`:

```ts
posthogAi: (chat?: string, ask?: string): string => combineUrl('/posthog-ai', { ask, chat }).url,
posthogAiHistory: (): string => '/posthog-ai/history',
```

Behind the feature flag `posthog-ai-sandbox` (Overview § 8), the `Scene.Max` route alias resolves to the new scene. Feature flag off → existing `/ai` → `scenes/max/`. On → existing `/ai` AND `/posthog-ai` → `scenes/posthog-ai/`. Same scene component handles both URL roots (so we don't break in-app links to `/ai` during the migration).

`urlToAction` bindings (mirror of `maxLogic.tsx:596-641`):

```ts
tabAwareUrlToAction(({ actions, values }) => ({
  [urls.posthogAiHistory()]: () => {
    if (!values.taskHistoryVisible) actions.toggleTaskHistory()
  },
  [urls.posthogAi()]: (_, search) => {
    if (search.ask && !search.chat && !values.question) {
      // Same logic as today: trigger askPostHogAi after a microtask delay.
      window.setTimeout(() => actions.askPostHogAi(String(search.ask), true, uiContext), 100)
      return
    }
    if (!search.chat && values.taskId) {
      actions.startNewChat()
    } else if (search.chat && search.chat !== values.taskId) {
      actions.openChat(search.chat)
    } else if (values.taskHistoryVisible) {
      actions.toggleTaskHistory()
    }
  },
})),

tabAwareActionToUrl(({ values }) => ({
  toggleTaskHistory: () => values.taskHistoryVisible ? [urls.posthogAiHistory()] : ...,
  startNewChat: () => [urls.posthogAi()],
  openChat: ({ taskId }) => [urls.posthogAi(taskId)],
  setTaskId: ({ taskId }) => taskId && taskId === values.frontendTaskId
    ? [urls.posthogAi(taskId), {}, router.values.location.hash, { replace: true }]
    : undefined,
})),
```

`tabAwareScene()` cache key is `tabId` — same as today. Each tab has its own draft question, open chat, history pane.

`Max.tsx` (already tab-aware via `useValues(maxLogic({ tabId }))`) becomes `PostHogAi.tsx`. The "is this side panel showing the same chat as this scene tab?" guard (`Max.tsx:48-72`) ports verbatim.

The `SceneExport` becomes:

```ts
export const scene: SceneExport = {
  component: PostHogAi,
  logic: posthogAiLogic,
}
```

Watch out: the side panel mount path (`tabId === 'sidepanel'`) mounts `posthogAiLogic({ tabId: 'sidepanel' })` once globally. The watcher logic (`runWatcherLogic({ taskId, runId })`) is shared with the scene mount via Kea's keyed-logic sharing. Two subscribers, one SSE, one bootstrap, two views — § 5.5.

---

## 11. Migration checklist

Phased, each phase shipped behind the `posthog-ai-sandbox` flag (Overview § 8). Within a phase, items are roughly ordered.

**Phase 0 — backend prerequisites** (mostly described elsewhere but a few flow through this spec):

- [ ] Permit `Task.repository = null` and `Task.github_integration = null` when `origin_product = "posthog_ai"`. Migration + serializer update (§ 3.1).
- [ ] Implement / confirm `GET /api/projects/{tid}/tasks/?origin_product=posthog_ai` filter (§ 3.2).
- [ ] Build `build_posthog_ai_system_prompt(team, user, task)` server-side and bake into Run creation (`04_PROMPTS.md`).
- [ ] Stand up `posthog-memory` MCP server (or fallback REST endpoint per § 8.2).

**Phase 1 — Core transport (this spec)**:

- [ ] Create `frontend/src/scenes/posthog-ai/` directory.
- [ ] Stub `posthogAiLogic.ts`, `posthogAiThreadLogic.ts`, `posthogAiGlobalLogic.ts`, `runWatcherLogic.ts`. Mount-only, no behavior.
- [ ] Wire `tabAwareScene()` + URL bindings on `posthogAiLogic` for `/posthog-ai`, `/posthog-ai/history`, `/posthog-ai/?chat=`, `/posthog-ai/?ask=`.
- [ ] Add `urls.posthogAi`, `urls.posthogAiHistory` to `frontend/src/scenes/urls.ts`.
- [ ] Add `Scene.PostHogAi` to `frontend/src/scenes/sceneTypes.ts` and route to `PostHogAi.tsx` behind feature flag.
- [ ] Port SSE parser. Either reuse `Twig/apps/code/src/main/services/cloud-task/sse-parser.ts` verbatim (drop into `frontend/src/scenes/posthog-ai/utils/sseParser.ts` — no deps) or replace with `eventsource-parser` from `lib/api`. Recommendation: port the small file.
- [ ] Implement `runWatcherLogic.ts`:
  - [ ] `WatcherState` reducers (§ 5.1).
  - [ ] `connectSse` listener with `fetch + ReadableStream` reading (§ 5.2).
  - [ ] `bootstrapWatcher` listener: REST → terminal-snapshot OR SSE+log-paginate-merge (§ 5.2).
  - [ ] `drainBufferedLogBatches` content-dedup (§ 5.3).
  - [ ] `scheduleReconnect` with 5-attempt cap, 2s base, 30s cap (§ 5.4).
  - [ ] `subscribe`/`unsubscribe` ref-counting (§ 5.5).
  - [ ] `sendCommand` JSON-RPC POST (§ 6.6, § 6.7).
  - [ ] Connection error mapping (§ 5.6).
  - [ ] Wire `cache.disposables.add(...)` for all timers, per project convention.
- [ ] Implement `posthogAiThreadLogic.ts`:
  - [ ] `messages` selector with ACP-event folding (§ 7.1, § 7.2).
  - [ ] `askPostHogAi`, `sendFollowUp`, `resumeAfterTerminal`, `cancelRun`, `respondToPermission` listeners (§ 6).
  - [ ] `enqueueQueuedMessage`, `consumeQueuedMessages`, `combineQueuedPrompts` (§ 6.3, § 6.4).
  - [ ] `isInitializing`, `errorOverlay`, `threadLoading`, `inputDisabled`, `submissionDisabledReason` selectors (§ 9.1, § 9.2).
  - [ ] Optimistic user-message append + echo dedup (§ 7.5).
- [ ] Implement `posthogAiGlobalLogic.ts` with `loadTaskHistory`, `loadTask`, `loadRun` loaders + the tool registry surviving unchanged from `maxGlobalLogic`.
- [ ] Build `PostHogAi.tsx` scene shell — port from `Max.tsx`, replacing `maxLogic` references.
- [ ] Build `PostHogAiInitializingView.tsx` with the 2-second delay rule (§ 9.1).
- [ ] Build `PostHogAiErrorOverlay.tsx` (§ 9.2).
- [ ] Port `ConversationHistory.tsx` → `TaskHistory.tsx` with the new `taskHistory` data source.
- [ ] Wire slash commands per § 8 (browser-handled paths first; `/init`, `/remember` may be Phase 2/3).
- [ ] Telemetry events (§ 9.4) — same names, new properties.
- [ ] Smoke test: send a string, see a response. (No PostHog data access yet; uses an echo MCP server per Overview Phase 1 plan.)

**Phase 2 — Context, Phase 3 — Rich UI, Phase 4 — Tool parity**: out of scope here. Trackable in `01_CONTEXT.md`, `03_RICH_UI.md`.

**Phase 5 — decommission**:

- [ ] Delete `frontend/src/scenes/max/` (post-soak).
- [ ] Remove `posthog-ai-sandbox` flag.
- [ ] Drop server-side `/conversations/` endpoints (after backend confirms no readers).

---

## 12. Open questions

These are the spec-level open questions that the team should resolve before or during Phase 1. Cross-cutting items live in `00_OVERVIEW.md § 9`.

1. **Permission mode default.** Recommendation: `acceptEdits` (§ 6.7). Confirm with the AI team. If they want zero friction, switch to `bypassPermissions` and rely on the agent's own restraint. If we want today's parity (approval for notebook creation, dashboards, etc.), `acceptEdits` matches.

2. **`origin_product` filter on `GET /tasks/`**. Is this already implemented backend-side? If not, this is a Phase 1 backend blocker. Owner: backend team.

3. **Trace id strategy** (§ 9.3). (a) `runId` only, or (b) per-turn `uuid()` passed via `_meta.trace_id`. Recommendation (b). Owner: AI + LLM Analytics.

4. **Slash command `/remember` path.** MCP-first (cleanest) or REST-first (faster to ship)? Recommendation: MCP-first if `posthog-memory` MCP server is ready by Phase 1; REST fallback otherwise (§ 8.2). Owner: AI.

5. **Two-tab queue sync.** Out-of-spec today — queue is per-tab. If users complain, look at `BroadcastChannel` or push queue state through `tabAwareScene`'s cache. Owner: punt.

6. **Cross-tab `runWatcherLogic` lifetime.** Kea's keyed logic is per-document, so two browser tabs each get their own watcher and their own SSE. This is *worse* than desktop where `CloudTaskService` is process-wide. Acceptable for v1; if SSE concurrency becomes a real cost, look at `SharedWorker`-backed transport. Owner: front-end + infra.

7. **Resume after disconnect of >5min**. `Last-Event-ID` only resumes if the Redis stream has the buffer. If the stream rotated, the watcher gets a fresh stream starting at `latest` — we'd miss events. Acceptable since content-dedup catches duplicates from the historical log on next bootstrap. Confirm: how long does the relay keep events in Redis? (Spec the buffer TTL in `00_OVERVIEW.md` or here.) Owner: backend.

8. **Approval ID instability across SSE reconnect.** A `permission_request` SSE event carries `requestId`. If the user reconnects while the agent has an outstanding permission_request, does the relay replay the event with the same `requestId`? It must (otherwise the user's `permission_response` can't resolve). Confirm: agent-server line 1886-2022 buffers `pendingPermissions` — so yes. But spell this out in the spec to avoid future regressions. Owner: AI.

9. **What if `current_mode_update` arrives mid-turn?** The agent's `permission_mode` shifts (e.g., model decided to switch to `plan` mode). Should the UI reflect this? Today's Max has `agentMode` lock semantics. New world: surface as a transient pill in the thread? Quiet? Owner: AI + product.

10. **Test fixtures.** Existing `frontend/src/scenes/max/testUtils.ts` defines mocks based on the today shape (`AssistantMessage`, `AssistantToolCallMessage`, …). The new shape (folded from `StoredLogEntry`) needs new fixtures — propose a `frontend/src/scenes/posthog-ai/testUtils.ts` that builds `StoredLogEntry[]` and produces ThreadMessages via the fold. Existing snapshot stories should be rewritten or moved alongside. Owner: this spec's implementer.
