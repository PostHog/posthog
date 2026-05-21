# 03 — Rich UI migration

This spec covers the migration of PostHog AI's *rich tool-call rendering* layer from the current `ui_payload`-on-`AssistantToolCallMessage` model onto the ACP `tool_call` / `tool_call_update` event stream produced by `@posthog/agent` inside the sandbox.

Read [`00_OVERVIEW.md`](./00_OVERVIEW.md) first.
The SSE transport, watcher, message reducer, and slash-command UI are owned by [`02_CORE.md`](./02_CORE.md) — that spec produces the typed event stream this spec consumes.
The set of MCP servers and their tool schemas is owned by [`04_PROMPTS.md`](./04_PROMPTS.md) — that spec defines which tool *names* show up on the wire; this spec defines what to *render* when they do.

Scope here: the *interception layer*, the *tool→renderer mapping table*, the *client-side tool replacement for `useMaxTool`*, the *approval and plan-mode UI rewiring*, the *progress-event wiring*, and the *file-by-file move plan* for the `messages/` folder.

---

## 1. Today: how ui_payload rendering works

### 1.1 The Thread.tsx dispatch path

Source: `posthog/frontend/src/scenes/max/Thread.tsx`.

The current flow:

1. `maxThreadLogic.threadGrouped` produces a flat `ThreadMessage[]` keyed by `id`. Each entry is one of `HumanMessage`, `AssistantMessage`, `AssistantToolCallMessage`, `FailureMessage`, `ArtifactMessage`, `MultiVisualizationMessage`, or a multi-question-form variant.
2. `Thread.tsx` maps over `threadGrouped` and dispatches each entry to a renderer based on type predicates (`isAssistantMessage`, `isAssistantToolCallMessage`, `isArtifactMessage`, `isMultiVisualizationMessage`, …) defined in `posthog/frontend/src/scenes/max/utils.ts`.
3. For `AssistantMessage`, the renderer additionally walks `message.tool_calls: AssistantToolCall[]` (enhanced with `status` + `result` + `updates` by `threadGrouped`) and renders each via `ToolCallsAnswer` → `AssistantActionComponent`. `AssistantActionComponent` is the "action chip" — icon, status, expandable substeps, optional widget.
4. The corresponding *tool result* is an `AssistantToolCallMessage` carrying `ui_payload` (a Record<toolName, payload>). `Thread.tsx` first filters out non-renderable payloads via `isRenderableUIPayloadTool` (`UIPayloadAnswer.tsx:51`), then either:
   - Renders the tool-call message inline at the top level of the thread (legacy path — `<UIPayloadAnswer toolCallId toolName toolPayload />`), or
   - Surfaces the payload *inside* the expandable accordion of the matching `AssistantActionComponent` via the same `UIPayloadAnswer` (Thread.tsx:1113–1131).
5. Special-case widgets (`SummarizeSessionsWidget`, `RecordingsWidget` driven by `filter_session_recordings`, `SessionSummarizationProgress`) are emitted by `TOOL_DEFINITIONS[toolName].displayFormatter()` (in `max-constants.tsx`) which returns `[text, { widget, args }]`. The widget tag is consumed by `getToolCallDescriptionAndWidget` (Thread.tsx:1652–1685).

The key invariants:

- Every renderable tool has its *args* (from `AssistantToolCall.args`) and its *result payload* (from `AssistantToolCallMessage.ui_payload`) co-located by `tool_call_id`. The `threadGrouped` selector pairs them.
- `status` is `pending` | `in_progress` | `completed` | `failed`. It is derived (today) from "did the tool result arrive yet?" plus a few special cases for streaming `updates`.
- `updates: string[]` is a per-tool-call live stream of progress strings (today: each one is a discrete SSE event with `type: 'update'` carrying a stringified payload). `SessionSummarizationProgress` reconstructs typed progress events from these.

### 1.2 messages/* renderer catalog

| File | Renders for | Inputs |
|---|---|---|
| `VisualizationArtifactAnswer.tsx` | `ArtifactMessage` with `VisualizationArtifactContent`. *Not* a tool-call renderer — driven by a dedicated message type. | `content: VisualizationArtifactContent`, `status`, `isEditingInsight` |
| `NotebookArtifactAnswer.tsx` | `ArtifactMessage` with `NotebookArtifactContent`. *Not* a tool-call renderer either. | `content: NotebookArtifactContent`, `status`, `artifactId` |
| `UIPayloadAnswer.tsx` | Top-level dispatcher for `AssistantToolCallMessage.ui_payload` and dangerous-op approvals. Currently handles `search_session_recordings`, `search_error_tracking_issues`, dangerous-ops. Exports `RecordingsWidget`, `ErrorTrackingFiltersWidget`, `SummarizeSessionsWidget`, `isRenderableUIPayloadTool`, `RENDERABLE_UI_PAYLOAD_TOOLS`. | `toolCallId`, `toolName`, `toolPayload` |
| `RecordingsFiltersSummary.tsx` | Header chip strip on the recordings widget — pure presentation of `RecordingUniversalFilters`. | `filters: RecordingUniversalFilters` |
| `ErrorTrackingIssueCard.tsx` | One row in the error-tracking widget list. | `issue: MaxErrorTrackingIssuePreview`, `showUserCount?` |
| `ErrorTrackingFiltersSummary.tsx` | Header chip strip on the error-tracking widget. | `filters: MaxErrorTrackingSearchResponse` |
| `MultiQuestionForm.tsx` (`MultiQuestionFormRecap`) | Read-only recap of a submitted `create_form` form (the *interactive* form lives in the input area). | `form: MultiQuestionForm`, `savedAnswers?`, `formStatus?` |
| `SessionSummarizationProgress.tsx` | Live progress display for `summarize_sessions` — derives state from a list of `sessions_discovered` / `progress` updates. | `updates: SessionSummarizationUpdate[]` |
| `MessageTemplate.tsx` | The shared chat-bubble shell (border, padding, avatar gutter). All renderers wrap in it. | `type: 'human' \| 'ai'`, `children`, `boxClassName?`, `wrapperClassName?`, `action?` |
| `maxErrorTrackingWidgetLogic.ts` | Kea logic bound by `<ErrorTrackingFiltersWidget>` to drive pagination of the issues list. | `MaxErrorTrackingWidgetLogicProps` (`toolCallId`, `filters`) |

All of these are *presentation-shaped* — they care about a payload shape, not about a transport. The migration just needs to feed them from a new source.

### 1.3 useMaxTool's client-side tool callback model

Source: `posthog/frontend/src/scenes/max/useMaxTool.ts`, `MaxTool.tsx`, `max-constants.tsx` (`ToolRegistration` interface), `maxGlobalLogic.tsx` (the `registeredToolMap` reducer, lines 144–157).

Today a scene component opts in via:

```tsx
useMaxTool({
    identifier: 'filter_session_recordings',
    context: { current_filters: filters },
    contextDescription: { text: 'Current recording filters', icon: <IconReplay /> },
    suggestions: ['Find rage clicks', '...'],
    callback: async (toolOutput, conversationId) => {
        // toolOutput is whatever the backend tool returned for this scene
        recordingsLogic.actions.setFilters(toolOutput)
    },
})
```

Mechanics:

- `useMaxTool` calls `maxGlobalLogic.actions.registerTool({ identifier, name, description, context, contextDescription, introOverride, suggestions, callback })` on mount.
- `registeredToolMap` is a `Record<identifier, ToolRegistration>` reducer. Plus there's a `STATIC_TOOLS` array (`maxGlobalLogic.tsx:27–73`) of always-on identifiers.
- Backend reads the registered set from the stream POST body (`contextual_tools`) so the agent can decide which tools to expose.
- When the agent calls the tool and returns a result, the frontend looks up `registeredToolMap[toolName].callback` and invokes it with the *parsed* `ui_payload` (today this happens inside `maxThreadLogic`).
- `context` (e.g. current filters) is included in the prompt round-trip so the agent has the scene state.

Both the *registration* and the *invocation* are deprecated by the new architecture but the *concept* (scenes participate in the agent's tool surface) is not.

### 1.4 Approval card flow

Source: `DangerousOperationApprovalCard.tsx`, `approvalOperationUtils.ts`, `maxThreadLogic` (reducers `pendingApprovalsData` and `resolvedApprovalStatuses`), `Thread.tsx:411–440` (the `approvalCardElements` `useMemo`).

Mechanics:

1. The backend tool decides "this is dangerous" and returns a `DangerousOperationResponse` shape (`schema-assistant-messages.ts:439–445`) as the tool's `ui_payload`. The shape: `{ status: 'pending_approval', proposalId, toolName, preview, payload }`.
2. `UIPayloadAnswer` detects this via `isDangerousOperationResponse(toolPayload)` and renders `<DangerousOperationApprovalCard operation={normalizeDangerousOperationResponse(toolPayload)} />`.
3. The *interactive* approve/reject UI is actually rendered in the chat input area (`DangerousOperationInput`, not in this spec's scope) — the card is a *summary chip* keyed by `proposalId`.
4. The card reads two reducers from `maxThreadLogic`: `pendingApprovalsData[proposalId]: PendingApproval` (backend state) and `resolvedApprovalStatuses[proposalId]` (optimistic local state). Either one having a non-`pending` status flips the card to "approved / rejected / responded".

The shapes that need to bridge to the ACP world:

| Field today | ACP equivalent |
|---|---|
| `proposalId` | `tool_call.toolCallId` *plus* `permission_request.requestId` (two ids, related but distinct — see § 5) |
| `toolName` | `tool_call.title` or `_meta.toolName` |
| `preview` | derived from `tool_call.content[]` (markdown / diff blocks) |
| `payload` | `tool_call.rawInput` |
| `decision_status` | `'pending' \| 'approved' \| 'rejected' \| 'auto_rejected'` — keyed off whether `permission_response` has been sent, plus `optionId` echo back |

---

## 2. Tomorrow: ACP-driven rendering

### 2.1 Event shapes

The watcher (`runWatcherLogic`, owned by `02_CORE.md` § 5) is the one source of truth.
It emits a typed event stream to `posthogAiThreadLogic`.
The events we care about for rich UI are (lifted from `CLOUD_AGENTS_FRONTEND_SPEC.md` §§ 5, 10.8–10.9):

```ts
// session/update with sessionUpdate = "tool_call"  (the first time the agent calls a tool)
interface AcpToolCallStart {
    sessionUpdate: 'tool_call'
    toolCallId: string
    title: string                           // e.g. "Reading data warehouse schema"
    kind?: string                           // 'read' | 'write' | 'edit' | 'execute' | 'think' | 'fetch' | 'search' | 'delete' | 'move' | 'switch_mode' | 'question' | string
    status?: 'pending' | 'in_progress' | 'completed' | 'failed'
    rawInput?: Record<string, unknown>      // the actual tool args
    locations?: ToolCallLocation[]
    content?: ToolCallContent[]
    _meta?: {
        toolName?: string                   // the MCP-qualified name, e.g. "posthog-data.read_taxonomy"
        mcpServer?: string                  // e.g. "posthog-data"
        claudeCode?: { toolName?: string }  // built-in Claude Code tool, e.g. "Write"
        [k: string]: unknown
    }
}

// session/update with sessionUpdate = "tool_call_update" (subsequent patches)
interface AcpToolCallUpdate {
    sessionUpdate: 'tool_call_update'
    toolCallId: string                      // matches a prior tool_call
    title?: string
    status?: 'pending' | 'in_progress' | 'completed' | 'failed'
    content?: ToolCallContent[]             // appended/replaced — see § 2.3
    rawOutput?: unknown                     // present on final update
    _meta?: { ... }
}

// session/update with sessionUpdate = "agent_message" or "agent_message_chunk"
interface AcpAgentMessage {
    sessionUpdate: 'agent_message' | 'agent_message_chunk'
    content: ToolCallContent[]               // typically [{ type: 'text', text: '...' }]
}

// permission_request event (separate kind on the cloud SSE frame — not session/update)
interface CloudPermissionRequest {
    kind: 'permission_request'
    requestId: string
    toolCall: {
        toolCallId: string
        title: string
        kind: string                         // e.g. "switch_mode" for plan approvals
        content?: ToolCallContent[]
        rawInput?: Record<string, unknown>
        _meta?: { ... }
    }
    options: CloudPermissionOption[]         // see § 5
}
```

`ToolCallContent` is the ACP variant union: `{ type: 'text', text }` | `{ type: 'markdown', markdown }` | `{ type: 'diff', path, oldText, newText }` | `{ type: 'image', ... }` | `{ type: 'resource_link', ... }` | etc.
Twig already parses these in `Twig/apps/code/src/renderer/features/task-detail/utils/cloudToolChanges.ts` — the `ParsedToolCall` interface there is structurally what we want.

### 2.2 The interception layer

New file: `posthog/frontend/src/scenes/posthog-ai/toolCallsLogic.ts`.

This logic owns the *current* state of all tool calls in the active Task, keyed by `toolCallId`.
It subscribes to `runWatcherLogic` (which forwards typed events out of the SSE/log stream) and merges `tool_call` and `tool_call_update` events into a single `ToolInvocation` record.

```ts
interface ToolInvocation {
    toolCallId: string
    runId: string                            // useful when filtering by current run
    title: string
    kind?: string
    status: 'pending' | 'in_progress' | 'completed' | 'failed'
    rawInput?: Record<string, unknown>
    /** Concatenated content blocks across the lifetime of the call. */
    content: ToolCallContent[]
    /** Captured final tool output if present on the last update. */
    rawOutput?: unknown
    /** Stream of `progress` notifications attached to this call (see § 6.1). */
    progress: PosthogProgressEvent[]
    locations?: ToolCallLocation[]
    /** MCP server identifier — derived from `_meta.mcpServer` if present, else inferred from title prefix. */
    mcpServer?: string
    /** MCP-qualified tool name, e.g. "posthog-data.read_taxonomy". Derived from `_meta.toolName`. */
    toolName?: string
    /** First-seen timestamp; preserved across updates. */
    firstSeenAt: string
    lastUpdatedAt: string
}

interface PendingPermission {
    requestId: string
    toolCallId: string                       // link back to the ToolInvocation
    options: CloudPermissionOption[]
    /** Local-optimistic resolution state. */
    resolution?:
        | { status: 'approved'; optionId: string }
        | { status: 'rejected'; optionId: string; customInput?: string }
}
```

Logic sketch:

```ts
interface ToolCallsLogicValues {
    invocationsByCallId: Record<string, ToolInvocation>
    /** Stable, ordered list — order = first-seen `firstSeenAt`. */
    invocations: ToolInvocation[]
    pendingPermissions: Record<string, PendingPermission>     // keyed by requestId
    permissionByToolCallId: Record<string, string>            // toolCallId → requestId
}

interface ToolCallsLogicActions {
    upsertToolCall: (event: AcpToolCallStart | AcpToolCallUpdate) => { event }
    recordPermissionRequest: (request: CloudPermissionRequest) => { request }
    recordProgress: (progress: PosthogProgressEvent) => { progress }
    resolvePermission: (requestId: string, optionId: string, customInput?: string) => {
        requestId
        optionId
        customInput
    }
    clearInvocationsForRun: (runId: string) => { runId }
}
```

Wiring (see `02_CORE.md` for the watcher contract):

- `runWatcherLogic` listener for `session/update` events: if `sessionUpdate ∈ {tool_call, tool_call_update}`, fire `upsertToolCall`. Reducer merges into `invocationsByCallId[toolCallId]` using the same `mergeToolCall` semantics as Twig's `cloudToolChanges.ts:43–61` — patch-wins-when-present.
- `runWatcherLogic` listener for `permission_request` SSE frames: fire `recordPermissionRequest`. Reducer puts it into `pendingPermissions[requestId]` and indexes by `toolCallId`.
- `runWatcherLogic` listener for `_posthog/progress` notifications: fire `recordProgress`. The progress payload carries `toolCallId` (see § 6.1); merge into `invocationsByCallId[toolCallId].progress[]`.
- Resolver: when `permission_response` is sent over the command channel (`02_CORE.md` § 6), set optimistic `resolution` on the pending permission. When the next status/SSE update echoes the resolution back (e.g. the next `tool_call_update` for the same `toolCallId` arriving in non-`pending` status), remove from `pendingPermissions` and rely on the invocation record.

The thread renderer (`posthog-ai/Thread.tsx`) does **not** read `invocationsByCallId` directly. Instead, `posthogAiThreadLogic.threadGrouped` *interleaves* tool invocations and agent messages into a single ordered list, using the timestamps emitted on each event.

### 2.3 toolCallId-keyed records in thread state

`posthogAiThreadLogic.threadGrouped` is structurally the same selector as today's, but its inputs are different.

Inputs:

- The persisted message log (built from `StoredLogEntry[]` returned by `GET /session_logs/`).
- The live invocation map from `toolCallsLogic`.
- The progress map.
- The pending-permission map.

It produces:

```ts
type PostHogAiThreadItem =
    | { kind: 'human'; id: string; content: string; ui_context?: MaxUIContext; timestamp: string }
    | { kind: 'ai'; id: string; content: string; timestamp: string; status: 'streaming' | 'completed' | 'failed' }
    | { kind: 'tool'; toolCallId: string; invocation: ToolInvocation; timestamp: string }
    | { kind: 'permission'; requestId: string; permission: PendingPermission; invocation: ToolInvocation; timestamp: string }
    | { kind: 'failure'; id: string; content: string; timestamp: string }
    | { kind: 'progress_group'; groupId: string; progress: PosthogProgressEvent[]; timestamp: string }
```

This is **the dispatch shape** for the new `Thread.tsx` — single source of truth, no second-pass enrichment in the renderer.

### 2.4 Rendering policy: when does a tool call become a card vs inline

Three policies, all keyed off `ToolInvocation.kind` (the ACP kind, not our backend-tool name):

1. **Inline action chip** — default. Render `<AssistantActionComponent>` (lifted from `Thread.tsx`, see § 8.2) with `icon`, `description`, `status`, `widget?`, `result?`. This is the equivalent of today's "tool call ribbon" inside `ToolCallsAnswer`.
2. **Full-width card** — for any tool whose result is "an artifact the user interacts with directly" — recordings list, error-tracking list, multi-question form, dashboard preview, visualization. Use `<MessageTemplate type="ai" wrapperClassName="w-full">` (the same shell `RecordingsWidget` uses today).
3. **Progress widget** — for any tool that has matching `_posthog/progress` notifications (see § 6). Render an inline action chip with the progress widget inlined via the same `displayFormatter[1].widget` mechanism that's in use today.

The decision is a single function `pickToolRendering(invocation: ToolInvocation): ToolRenderingMode` defined in `posthog-ai/toolRenderingPolicy.ts` and driven by a lookup table whose source of truth is the mapping table in § 3.

```ts
type ToolRenderingMode =
    | { mode: 'chip'; renderer?: ChipRendererKey; widget?: 'recordings' | 'session_summarization' | 'plan' }
    | { mode: 'card'; renderer: CardRendererKey }
    | { mode: 'fallback' }                   // generic content-block dump

type ChipRendererKey = 'planning' | 'switch_mode' | 'generic'
type CardRendererKey =
    | 'recordings_search'
    | 'error_tracking_search'
    | 'visualization'
    | 'notebook'
    | 'multi_question_form'
    | 'summarize_sessions'
    | 'dashboard'
    | 'session_summary_link'
```

`pickToolRendering` keys off `invocation.toolName` first (the MCP-qualified name), falling back to `invocation.kind` second, falling back to `{ mode: 'fallback' }`.

---

## 3. Tool → renderer mapping

This is the canonical mapping table.
Anything not in this table renders via the generic fallback in § 3.2.

The MCP server column is owned by [`04_PROMPTS.md`](./04_PROMPTS.md) — the names are my best guess; expect minor renames.
The "renderer file" column points at the file that exists today (which we will keep, with at most a thin adapter — see § 8).

### 3.1 Complete table

| # | Backend tool (today) | MCP server | MCP tool name | ACP `tool_call.kind` | Renderer (today's file) | Rendering mode | `rawInput` → renderer props | `tool_call_update.content` / `rawOutput` → renderer props |
|---|---|---|---|---|---|---|---|---|
| 1 | `read_taxonomy` | `posthog-data` | `read_taxonomy` | `read` | inline chip — no body | chip / generic | shown in expanded substeps as JSON (`rawInput.entity`, `rawInput.event_name`, `rawInput.property_name`) | result text → expanded substeps, no widget |
| 2 | `read_data` (subtools: `billing_info`, `data_warehouse_schema`, `data_warehouse_table`, `artifacts`, `insight`, `dashboard`) | `posthog-data` | `read_data` (single tool, subtype via `rawInput.kind` / `rawInput.query.kind`) | `read` (default) or `execute` (when `rawInput.query.execute`) | inline chip + conditional card for `insight` / `dashboard` subtypes | chip / `visualization` card when subtype = `insight` and result is a query | `rawInput.query.kind` switches the chip text via `displayFormatter` (same as today). For `kind === 'insight'` with `execute: true`, pass the rebuilt `InsightVizNode \| DataVisualizationNode` to `VisualizationArtifactAnswer` | result content includes the query node — see § 3.1.7 for assembly |
| 3 | `list_data` | `posthog-data` | `list_data` | `read` | inline chip — no body | chip / generic | `rawInput.kind`, `rawInput.offset` drive the description ("Listing surveys (page 2)…") | none — text only |
| 4 | `search` (subtools: `docs`, `insights`, `dashboards`, `cohorts`, `actions`, `experiments`, `feature_flags`, `notebooks`, `surveys`, `error_tracking_issues`, `all`) | `posthog-search` | `search` | `search` | inline chip — no body | chip / generic | `rawInput.kind` switches chip text | result content → expanded substeps as JSON |
| 5 | `search_session_recordings` *(today contextual)* | `posthog-replay` | `search_session_recordings` | `search` | `messages/UIPayloadAnswer.tsx → RecordingsWidget` | card / `recordings_search` | none (server-side filters built from `rawInput.query`) | `rawOutput.filters: RecordingUniversalFilters` → `<RecordingsWidget filters />`. Reuse `MaxRecordingsLogic` props as-is. |
| 6 | `filter_session_recordings` *(today client-callback tool — see § 4)* | client-hosted MCP (see § 4) | `filter_session_recordings` | `write` | inline chip with `recordings` widget (the side preview that mutates the scene's filters) | chip / `recordings` widget | `rawInput.recordings_filters: RecordingUniversalFilters` → widget shows the filters the agent *proposes*; the scene callback applies them | none — the *act* of calling this tool is the result; widget shows the proposed filters |
| 7 | `search_error_tracking_issues` | `posthog-error-tracking` | `search_issues` | `search` | `messages/UIPayloadAnswer.tsx → ErrorTrackingFiltersWidget` | card / `error_tracking_search` | server-side filters built from `rawInput` | `rawOutput: MaxErrorTrackingSearchResponse` → `<ErrorTrackingFiltersWidget filters />`. `maxErrorTrackingWidgetLogic` props remain (`toolCallId`, `filters`). |
| 8 | `filter_error_tracking_issues` | client-hosted MCP | `filter_error_tracking_issues` | `write` | inline chip (no widget today) | chip / generic | `rawInput` → applied to scene via client callback | none |
| 9 | `find_error_tracking_impactful_issue_event_list` | `posthog-error-tracking` | `find_impactful_issues` | `search` | inline chip — no body | chip / generic | `rawInput` shown in expanded substeps | result list → expanded substeps |
| 10 | `summarize_sessions` | `posthog-replay` | `summarize_sessions` | `execute` | `messages/SessionSummarizationProgress.tsx` (inline progress widget) + `messages/UIPayloadAnswer.tsx → SummarizeSessionsWidget` (out-of-accordion CTA) | chip / `session_summarization` widget + persistent CTA on completion | `rawInput.summary_title` → chip text | live `_posthog/progress` notifications drive the widget (see § 6); on completion `rawOutput.session_group_summary_id` → `SummarizeSessionsWidget` CTA |
| 11 | `experiment_session_replays_summary` | `posthog-experiments` | `summarize_experiment_replays` | `execute` | same as #10 | chip / `session_summarization` widget | same wiring as #10 | same wiring as #10 |
| 12 | `experiment_results_summary` | `posthog-experiments` | `summarize_experiment_results` | `execute` | inline chip — no body | chip / generic | `rawInput.experiment_id` → chip text | result markdown → expanded substeps |
| 13 | `analyze_user_interviews` | `posthog-user-interviews` | `analyze_interviews` | `execute` | inline chip | chip / generic | — | result text in expanded substeps |
| 14 | `create_user_interview_topic` | client-hosted MCP (writes to scene) | `create_interview_topic` | `write` | inline chip | chip / generic | client callback applies to scene | — |
| 15 | `create_insight` *(today contextual)* | client-hosted MCP | `create_or_edit_insight` | `write` | inline chip — *plus* the scene-level `<VisualizationArtifactAnswer>` triggered from the *artifact* the tool produces | chip / generic; the actual rendering of the produced insight goes through an `ArtifactMessage`-equivalent (see § 3.1.6) | `rawInput.query` → preview / client callback | `rawOutput` is the saved-insight short ID; the *visualization* shows up as a separate `ArtifactMessage`-shaped event (see below) |
| 16 | `upsert_dashboard` | `posthog-dashboards` | `upsert_dashboard` | `write` | `messages/UIPayloadAnswer.tsx` extension — *today* a plain "Created the dashboard" chip; **new**: a real card with a dashboard preview. **TODO — confirm with AI team** if the card already exists in the codebase. | chip / `dashboard` card (new — extends current behavior) | `rawInput.action.dashboard_id` (when editing) | `rawOutput.dashboard_id` → link out, optional embedded preview |
| 17 | `create_notebook` | `posthog-notebook` | `create_notebook` | `write` | `messages/NotebookArtifactAnswer.tsx` (today reached via `ArtifactMessage`, not via `ui_payload`) | card / `notebook` | `rawInput.draft_content` (when set) | `rawOutput` carries the `NotebookArtifactContent` *plus* `artifact_id`. The renderer assembles a `NotebookArtifactAnswer` props bag from these. See § 3.1.5 for assembly. |
| 18 | `create_form` | `posthog-forms` (or a built-in agent capability — **TODO — confirm with AI team**) | `create_form` | `question` | input area (interactive) + `messages/MultiQuestionForm.tsx → MultiQuestionFormRecap` (read-only recap in the chat) | card / `multi_question_form` *only* for the recap; the *interactive* form is in input area (owned by `02_CORE.md` § 8) | `rawInput.questions: MultiQuestionForm['questions']` → form definition | `rawOutput.answers: Record<string,string\|string[]>`, `rawOutput.status` → recap props |
| 19 | `create_survey` | `posthog-surveys` or client-hosted MCP | `create_survey` | `write` | inline chip + scene side-effect (the scene's `useMaxTool` callback opens the survey form) | chip / generic | `rawInput` → client callback applies to scene | result → link |
| 20 | `edit_survey` | client-hosted MCP | `edit_survey` | `write` | inline chip | chip / generic | `rawInput` → client callback | — |
| 21 | `analyze_survey_responses` | `posthog-surveys` | `analyze_responses` | `execute` | inline chip | chip / generic | `rawInput.survey_id` → chip text | result text → substeps |
| 22 | `create_message_template` | client-hosted MCP | `create_message_template` | `write` | inline chip + scene callback | chip / generic | `rawInput` → client callback | — |
| 23 | `create_hog_function_filters` | client-hosted MCP | `create_hog_function_filters` | `write` | inline chip + scene callback | chip / generic | `rawInput` → client callback | — |
| 24 | `create_hog_transformation_function` | client-hosted MCP | `create_hog_transformation_function` | `write` | inline chip + scene callback | chip / generic | `rawInput` → client callback | — |
| 25 | `create_hog_function_inputs` | client-hosted MCP | `create_hog_function_inputs` | `write` | inline chip + scene callback | chip / generic | `rawInput` → client callback | — |
| 26 | `fix_hogql_query` | client-hosted MCP | `fix_hogql_query` | `write` | inline chip + scene callback (the SQL editor swaps in the corrected query) | chip / generic | `rawInput.broken_query` → chip text | `rawOutput.fixed_query` → applied via callback |
| 27 | `execute_sql` | client-hosted MCP (the SQL editor *is* the runtime) | `execute_sql` | `execute` | inline chip; **plus**: SQL pretty-print in the substeps via `executedSQLQuery` (see `Thread.tsx:1015–1020`, `:1131–1138`) | chip / generic | `rawInput.query` → SQL block in substeps | `rawOutput` → "Executed SQL" |
| 28 | `filter_revenue_analytics` | client-hosted MCP | `filter_revenue_analytics` | `write` | inline chip + scene callback | chip / generic | `rawInput` → client callback | — |
| 29 | `filter_web_analytics` | client-hosted MCP | `filter_web_analytics` | `write` | inline chip + scene callback | chip / generic | `rawInput` → client callback | — |
| 30 | `web_analytics_doctor` | `posthog-doctor` | `diagnose_web_analytics` | `execute` | inline chip | chip / generic | `rawInput.team_id` → chip text | result markdown → substeps |
| 31 | `diagnose_proxy` | `posthog-doctor` | `diagnose_proxy` | `execute` | inline chip + scene callback | chip / generic | — | result markdown → substeps |
| 32 | `create_feature_flag` | client-hosted MCP | `create_feature_flag` | `write` | inline chip + scene callback | chip / generic | `rawInput` → client callback | result → link |
| 33 | `create_experiment` | client-hosted MCP | `create_experiment` | `write` | inline chip + scene callback | chip / generic | `rawInput` → client callback | result → link |
| 34 | `upsert_alert` | client-hosted MCP | `upsert_alert` | `write` | inline chip + scene callback | chip / generic | `rawInput.action` (with `alert_id` for edits) | result → link |
| 35 | `create_task` / `run_task` / `get_task_run` / `get_task_run_logs` / `list_tasks` / `list_task_runs` / `list_repositories` | `posthog-tasks` | each maps 1:1 (`create_task`, …) | `read` / `write` | inline chip — no body today | chip / generic | per-tool inputs shown in substeps | per-tool outputs shown in substeps |
| 36 | `todo_write` | `posthog-tasks` *or* built into systemPrompt as a planning tool — **TODO — confirm with AI team** | `todo_write` | `think` | `Thread.tsx` `PlanningAnswer` (today: a custom planning UI with `LemonCheckbox` per todo) | special chip / `planning` | `rawInput.todos: Array<{content, status, activeForm}>` → planning list | none — the *args* are the result |
| 37 | `task` (subagent runner) | built-in to the agent runtime (not an MCP server) | — | `execute` | inline chip — title is "Running a task: …" | chip / generic | `rawInput.title` → chip text | result → substeps |
| 38 | `switch_mode` | not an MCP tool — **promoted to a `permission_request` with `kind: 'switch_mode'`** (see § 5.2) | — | `switch_mode` | `PlanApprovalCard.tsx` (new — see § 5.2) | card / `plan` | `rawInput.new_mode` → which mode is being entered | none — the *act* of selecting a permission option is the result |
| 39 | `manage_memories` | `posthog-memories` | `manage_memories` | `write` | inline chip | chip / generic | `rawInput.action` (create/update/delete), `rawInput.text` | result confirmation → substeps |
| 40 | `call_mcp_server` | *the agent natively calls MCP servers; this LangGraph wrapper goes away entirely.* The fact that a user-installed MCP server got called now shows up as a generic `tool_call` with `_meta.mcpServer = '<user-installed-slug>'`. | — | per the MCP server's tool | inline chip — title from the MCP tool's name | chip / generic (fallback path) | `rawInput` shown raw in substeps | result content blocks shown raw in substeps |
| 41 | `finalize_plan` | not an MCP tool — replaced by `switch_mode` permission_request to "execution" mode (see § 5.2) | — | `switch_mode` | same as #38 | card / `plan` | — | — |
| 42 | `web_search` | built into the LLM provider (Anthropic web search 20250305 in current code) | — | `search` | inline chip with `updates[]` showing search results as Markdown links | chip / generic | `rawInput.query` → chip text | each result becomes a substep |
| 43 | `search_llm_traces` | `posthog-llm-analytics` | `search_traces` | `search` | inline chip | chip / generic | `rawInput` → chip text | result → substeps |
| 44 | `run_hog_eval_test` | `posthog-llm-analytics` | `run_hog_eval_test` | `execute` | inline chip + scene callback | chip / generic | `rawInput` → client callback | result → substeps |

#### 3.1.5 Notebook artifact assembly

`NotebookArtifactAnswer` (a.k.a. the rich notebook renderer) is *not* fed from `ui_payload` today — it's fed from a dedicated `ArtifactMessage` carrying `NotebookArtifactContent.blocks: (MarkdownBlock | VisualizationBlock | SessionReplayBlock | DocumentBlock | ErrorBlock | LoadingBlock)[]`.

In the new world there is no `ArtifactMessage` type.
The flow is:

1. Agent calls the `posthog-notebook.create_notebook` MCP tool.
2. The MCP server streams `tool_call_update` events with `content` blocks. Each content block is one of the existing notebook block types (or normalized to one).
3. On completion, `rawOutput` contains `{ notebook_id, artifact_id, is_saved, title, ... }`.
4. The renderer assembles `NotebookArtifactContent` props by mapping `content[]` → `blocks[]` and `rawOutput` → metadata.

Adapter function (sketch):

```ts
function invocationToNotebookContent(inv: ToolInvocation): NotebookArtifactContent | null {
    if (inv.toolName !== 'posthog-notebook.create_notebook') return null
    const blocks = inv.content.flatMap(adaptToNotebookBlock)
    return {
        blocks,
        notebook_id: inv.rawOutput?.notebook_id,
        is_saved: inv.rawOutput?.is_saved ?? false,
        title: inv.rawOutput?.title,
    }
}
```

`adaptToNotebookBlock` is the only new code — it maps an ACP `ToolCallContent` block to a `NotebookArtifactContent` block. `{ type: 'markdown' }` → `MarkdownBlock`. `{ type: 'resource_link', ... }` with a recognized URL → `SessionReplayBlock` or `VisualizationBlock`. Everything else → `DocumentBlock` as a fallback.

#### 3.1.6 Visualization assembly

Same shape as notebook.
The agent calls `posthog-data.read_data` (subtype `insight` with `execute: true`) or a dedicated `posthog-insights.preview_insight` MCP tool (**TODO — confirm with AI team**).
The renderer assembles a `VisualizationArtifactContent`:

```ts
function invocationToVisualizationContent(inv: ToolInvocation): VisualizationArtifactContent | null {
    if (!isVizCapableInvocation(inv)) return null
    const queryBlock = inv.content.find(c => c.type === 'json' && c.subtype === 'insight_viz_node')
    if (!queryBlock) return null
    return {
        query: queryBlock.json as InsightVizNode | DataVisualizationNode,
        source: ArtifactSource.Agent,
        // ...other fields preserved
    }
}
```

The block subtype convention (`type: 'json', subtype: 'insight_viz_node'`) is a PostHog-side extension to `ToolCallContent`. Define it in `posthog-ai/types.ts` once and reuse for every PostHog-typed payload (insight, dashboard, recording-filters, error-tracking-search-response).

#### 3.1.7 Inline data results (no widget)

Many `posthog-data` tools return *plain text* tool results.
These don't need a widget — they belong in the existing "expanded substeps" of `AssistantActionComponent` (the inline `<MarkdownMessage>` block rendered when the chip is expanded; see `Thread.tsx:1077–1104`).

The adapter is: `inv.content` where `content[i].type === 'text' | 'markdown'` → concatenated and rendered with `<MarkdownMessage content={…} />`.

### 3.2 Unknown / fallback

If a tool call's `toolName` is not in the mapping table (e.g. a user-installed MCP server, or a brand-new tool we haven't mapped yet), render via:

```tsx
<GenericToolCallChip
    title={invocation.title}
    kind={invocation.kind}
    status={invocation.status}
    rawInput={invocation.rawInput}
    content={invocation.content}
/>
```

Behavior:

- Header: `invocation.title` (e.g. "Reading data warehouse schema") — falls back to `${invocation.toolName ?? 'Tool'}`.
- Status icon: same logic as `AssistantActionComponent` today.
- Body (expanded by default while `status === 'in_progress'`; collapsed when `completed`):
  - Render `content` blocks via `renderToolCallContentBlock(block)` — text/markdown → `MarkdownMessage`, diff → existing `PatchedFileDiff` (won't apply for Max), image → `<img>`, resource_link → link, json → `CodeSnippet language={JSON}`.
  - "Inputs" sub-section (collapsed by default) with `rawInput` as JSON in a `CodeSnippet`.

This matches what today's `AssistantActionComponent` already does in its bottom half (`Thread.tsx:1113–1205`) — basically reuse that block as `GenericToolCallChip`.

---

## 4. Client-side MCP tools (replacing useMaxTool)

This is the substantial new design question.

Today (§ 1.3) `useMaxTool` registers a *scene-local callback* — when the agent's response carries a `ui_payload` for the registered tool, the frontend invokes the callback locally, e.g. to mutate filters in the page.

In the new architecture the agent never sends `ui_payload` — it issues an ACP `tool_call`.
Two architectures can deliver this to a browser-side handler:

### 4.1 Option A: browser-hosted MCP server bridged via the relay

The browser hosts a tiny in-process MCP server.
The agent in the sandbox sees this MCP server via the relay and treats it like any other MCP tool.

Plumbing:

1. On mount, `usePostHogAiTool()` registers a tool spec `{ name, description, inputSchema }` *plus* a local handler `async (args) => result` in a `clientMcpRegistry` Kea logic.
2. `posthogAiThreadLogic` exposes the current list of registered client tools to the backend when starting a run (via the `Task` state's `client_mcp_tools` — see `02_CORE.md` § 7 for the channel — or via `_posthog/refresh_session` between turns).
3. The sandbox-side relay knows the run has a "client MCP" channel; when the agent calls `client-mcp.<toolName>` with args, the sandbox forwards the call to PostHog cloud, which forwards to the browser via a new SSE frame `client_mcp_invoke`.
4. The browser executes the handler, returns the result via `POST /command/` `method: client_mcp_result, params: { invocationId, result | error }`.
5. The relay returns the result to the agent.

Pros: matches the MCP model end-to-end; user-installed MCPs and scene-hosted tools are indistinguishable from the agent's POV; works with any agent runtime that speaks MCP.

Cons: meaningful infrastructure work — needs a new SSE frame type, a new command method, a new sandbox-side relay path. Not yet in `CLOUD_AGENTS_FRONTEND_SPEC.md` § 6.1's command methods list.

### 4.2 Option B: backend-mediated "client tool" content blocks

Keep the agent oblivious. The systemPrompt declares the contract: "to mutate the user's current scene, emit a special content block of `type: 'client_tool_request'` with `{ tool: '<name>', args: {...} }`."

Plumbing:

1. The agent emits `agent_message` content blocks where one block is `{ type: 'client_tool_request', tool, args, invocationId }`.
2. `posthogAiThreadLogic` listener intercepts these blocks on arrival, looks up `clientToolRegistry[tool]`, runs the handler, and (optionally) sends the result back via `POST /command/` `method: user_message` carrying a follow-up "Result: …" prompt.
3. The renderer suppresses the `client_tool_request` block from the visible message (so the user just sees the side-effect plus an inline `<AssistantActionComponent>` recording what the agent asked to do).

Pros: zero infra changes — the agent just emits a content block; the frontend reacts.

Cons: not a real MCP tool, so the agent's tool schema can't reason about it; type-safety is by convention. The agent can hallucinate the tool name. The result has to be re-injected as a user message (or a chat-side ACK), which can disrupt streaming.

### 4.3 Recommendation

**Pursue Option A.** The client-side tools are *real* tools the agent should be able to discover and call programmatically (and have a typed input schema). The infrastructure work is small (one SSE frame, one command method) and pays for itself the first time we need it for any other browser-side capability (e.g. "let the agent ask the user to confirm an action" without a permission round-trip).

Option B can be a *temporary backup* for very simple scene callbacks if we want to ship before A is ready — but treat it as transitional.

**For both options the systemPrompt change is owned by `04_PROMPTS.md` § 6.** This spec just consumes whichever channel exists.

### 4.4 The new `usePostHogAiTool.ts` hook

New file: `posthog/frontend/src/scenes/posthog-ai/usePostHogAiTool.ts`.

Public API stays compatible with today's `useMaxTool` so existing call sites only need to swap the import.

```ts
import type { JsonSchema } from '~/queries/schema/json-schema'

export interface UsePostHogAiToolOptions<TArgs = unknown, TResult = unknown> {
    /** MCP tool name as seen by the agent. Use the same `identifier` strings as TOOL_DEFINITIONS today
     *  for one-to-one parity during the migration window. */
    identifier: keyof typeof TOOL_DEFINITIONS

    /** Input schema for the MCP tool. Required when registering — the agent uses this to construct args. */
    inputSchema: JsonSchema

    /** Local handler — runs in the browser when the agent calls this tool. */
    handler: (args: TArgs) => TResult | Promise<TResult>

    /** Live context to attach to the registration (visible to the agent as MCP "resources" or as systemPrompt insertions — see 04_PROMPTS § 7). */
    context?: Record<string, unknown>

    /** Display-only label for the input area chip showing "the agent can use this". */
    contextDescription?: { text: string; icon: JSX.Element }

    /** Suggested prompts surfaced when Max is opened from this scene. */
    suggestions?: string[]

    /** When false, the tool is unregistered. */
    active?: boolean

    /** Initial prompt to seed the chat with on open. */
    initialMaxPrompt?: string

    /** Side-effect: called when the side-panel Max opens because of this scene. */
    onMaxOpen?: () => void

    /** Optional override for the introduction shown when Max is opened from this scene. */
    introOverride?: { headline: string; description: string }
}

export interface UsePostHogAiToolReturn {
    isMaxOpen: boolean
    openMax: (() => void) | null
}

export function usePostHogAiTool<TArgs, TResult>(
    options: UsePostHogAiToolOptions<TArgs, TResult>
): UsePostHogAiToolReturn
```

Implementation sketch:

```ts
// inside usePostHogAiTool — pseudocode
const { registerClientTool, deregisterClientTool, updateClientToolContext } = useActions(clientMcpRegistryLogic)

useEffect(() => {
    if (!active) return
    registerClientTool({
        identifier,
        inputSchema,
        handler,
        context,
        contextDescription,
        suggestions,
        introOverride,
    })
    return () => deregisterClientTool(identifier)
}, [active, identifier, inputSchema, handler, /* ... */])

// Update context independently (cheap — just patches state, doesn't re-register).
useEffect(() => {
    if (!active) return
    updateClientToolContext({ identifier, context })
}, [active, identifier, JSON.stringify(context)])
```

`clientMcpRegistryLogic` (new) maintains the same shape as today's `registeredToolMap` but with the addition of `inputSchema` and an actual `handler` function (kept in a `cache` so kea doesn't try to serialize it).

The hook's `openMax` behavior is unchanged — it starts a new conversation, surfaces suggestions, opens the side panel. The only thing that changes underneath is the transport.

#### 4.4.1 Existing call sites that need migrating

Inventory (from a quick `grep -rn "identifier:" frontend/src/scenes`):

- `scenes/data-warehouse/editor/QueryWindow.tsx:215` — `execute_sql`
- `scenes/data-warehouse/editor/SQLEditor.tsx:412` — `execute_sql`
- `scenes/insights/InsightPageHeader.tsx:65, :80` — `read_data`, `upsert_alert`
- `scenes/settings/environment/ManagedReverseProxy.tsx:69` — `diagnose_proxy`
- `scenes/experiments/Experiments.tsx:554` — `create_feature_flag`
- `scenes/experiments/components/SummarizeExperimentButton.tsx:61` — `experiment_results_summary`
- `scenes/experiments/hooks/useSessionReplaySummaryMaxTool.ts:40` — `experiment_session_replays_summary`
- `scenes/dashboard/DashboardHeader.tsx:62` — `upsert_dashboard`
- `scenes/web-analytics/WebAnalyticsScene.tsx:15` — `web_analytics_doctor`
- `scenes/surveys/{Survey, Surveys, wizard/SurveyWizard, wizard/steps/TemplateStep, components/SurveyOpportunityButton, components/AnalyzeResponsesButton, components/empty-state/SurveysEmptyState}.tsx` — `create_survey`, `edit_survey`, `analyze_survey_responses`
- `scenes/hog-functions/{filters, configuration/components/HogFunctionCode, configuration/components/HogFunctionInputs}.tsx` — `create_hog_function_filters`, `create_hog_transformation_function`, `create_hog_function_inputs`

Migration mechanics per call site:

1. Swap the import `useMaxTool` → `usePostHogAiTool`.
2. Add an `inputSchema` (write it once per identifier — collect them in `posthog-ai/clientToolSchemas.ts`).
3. Adapt `callback: (toolOutput, conversationId) => …` → `handler: (args) => … return result`. The shape change is from "you receive the tool's *result payload* and apply it" to "you receive the tool's *args* and *return* a result". This is a meaningful semantic flip — confirm each call site individually.
4. Delete the now-unused `MaxTool` wrapper UI (the `+` overlay button) — replace with the new contextual cue (owned by `02_CORE.md`'s context topbar).

There are ~20 call sites total. Each is 3–10 lines of change.

---

## 5. Approval & plan-mode UIs

### 5.1 permission_request → DangerousOperationApprovalCard rewiring

The card UI in `DangerousOperationApprovalCard.tsx` is *kept*. Only the data feed changes.

Flow today:
```
backend tool → ui_payload with status='pending_approval' → UIPayloadAnswer detects it
   → DangerousOperationApprovalCard rendered inline
   → reads maxThreadLogic.pendingApprovalsData[proposalId] for resolution
```

Flow tomorrow:
```
agent calls MCP tool → MCP tool returns an ACP requestPermission call
   → cloud relay broadcasts `permission_request` SSE frame (see CLOUD_AGENTS_FRONTEND_SPEC § 5.3.4)
   → toolCallsLogic.recordPermissionRequest indexes by requestId AND toolCallId
   → posthogAiThreadLogic.threadGrouped surfaces a `kind: 'permission'` item next to the matching `kind: 'tool'` item
   → DangerousOperationApprovalCard.tsx is rendered with adapted props
```

Adapter `permissionRequestToDangerousOperation(perm, invocation)`:

```ts
function permissionRequestToDangerousOperation(
    perm: CloudPermissionRequest,
    invocation: ToolInvocation | undefined
): DangerousOperationResponse {
    return {
        status: PENDING_APPROVAL_STATUS,
        proposalId: perm.requestId,                            // NB: was proposalId, now requestId — same meaning
        toolName: perm.toolCall.title || invocation?.toolName || perm.toolCall.kind,
        preview: extractPreview(perm.toolCall.content),         // first text/markdown block, falling back to title
        payload: (perm.toolCall.rawInput ?? {}) as Record<string, any>,
    }
}
```

The card's reducer references (`pendingApprovalsData`, `resolvedApprovalStatuses` in `maxThreadLogic`) get replaced by their `posthogAiThreadLogic` equivalents — same shape, different owner:

- `pendingApprovalsData: Record<requestId, PendingPermission>` — owned by `toolCallsLogic` (§ 2.2).
- `resolvedApprovalStatuses: Record<requestId, { status: 'approved' | 'rejected'; feedback?: string }>` — owned by `posthogAiThreadLogic` reducer keyed off the optimistic `resolution` field and the result echo from the next `tool_call_update`.

The interactive approve/reject UI in the input area (today: `DangerousOperationInput`) is **owned by `02_CORE.md` § 6** — it dispatches `permission_response` JSON-RPC commands. This spec only owns the *in-thread chip*.

### 5.2 switch_mode permissions → PlanApprovalCard

Today: `switch_mode` is a *tool*. The agent calls it; the backend's reducer literally switches modes. There's no user-facing approval moment.

Tomorrow (per `CLOUD_AGENTS_FRONTEND_SPEC § 10.7`): the agent-server intercepts ACP `requestPermission` calls with `toolCall.kind === "switch_mode"` and *always* relays them as `permission_request` events — even in `bypassPermissions` mode. This is how the "approve plan before executing" gate works in PostHog Code.

We want the same gate for PostHog AI's plan mode:

1. The plan-mode prompt instructs the agent to call `requestPermission` with `kind: 'switch_mode'` and `_meta: { fromMode: 'plan', toMode: 'execution' }` once the plan is ready.
2. The cloud SSE delivers a `permission_request` frame with `toolCall.kind === 'switch_mode'`.
3. `posthogAiThreadLogic.threadGrouped` surfaces a `{ kind: 'permission', permission, invocation }` item *at the position of the corresponding `tool_call` event*.
4. The renderer dispatches to `PlanApprovalCard.tsx` (new) instead of `DangerousOperationApprovalCard.tsx`.

`PlanApprovalCard.tsx`:

```tsx
interface PlanApprovalCardProps {
    permission: PendingPermission
    /** Optional: the preceding todo_write / planning content to show as the plan summary. */
    planContent?: PlanningStep[]
}

export function PlanApprovalCard({ permission, planContent }: PlanApprovalCardProps): JSX.Element
```

Renders:

- Header: "PostHog AI has prepared a plan. Review before executing."
- Plan summary: re-use `PlanningAnswer` (today in `Thread.tsx:843–928`) — extract to `posthog-ai/messages/PlanningAnswer.tsx` for reuse here.
- Action row: one `LemonButton` per `permission.options[]` entry. Map `optionId` → label using the kind mapping in § 5.3.
- Once a button is clicked: optimistically set `permission.resolution`, fire `posthogAiThreadLogic.actions.respondToPermission(requestId, optionId, customInput?)` (which dispatches `POST /command/ permission_response`).

Where does the plan content come from? Walk backwards from the `permission_request`'s `toolCallId` in the thread and pick up the most recent `tool_call` with `toolName === 'posthog-tasks.todo_write'` (or built-in todo) — its `rawInput.todos` is the plan.

If no plan content is found, just show "Approve plan and continue?" with no body — better than nothing.

### 5.3 Option-kind mapping table

The cloud emits options with kinds: `allow_once | allow_always | reject | reject_with_feedback` (and the sandbox may emit custom kinds via `_meta.customKind`).

Bridge table:

| Cloud option `kind` | UI label (PostHog AI) | Action |
|---|---|---|
| `allow_once` | "Approve" | `respondToPermission(requestId, optionId)`. Optimistic status `'approved'`. |
| `allow_always` | "Always approve this tool" | Same, plus persist "auto-approve for this tool name" in user prefs (out of scope for migration — keep behavior parity by ignoring the persistence today). |
| `reject` | "Decline" | `respondToPermission(requestId, optionId)`. Optimistic status `'rejected'`. |
| `reject_with_feedback` | "Decline with feedback…" | Opens a small inline textbox; on submit, `respondToPermission(requestId, optionId, customInput)`. Optimistic status `'rejected'`, `feedback` = `customInput`. |
| (any other) | "{ option.name }" | Pass through; treat like `allow_once`. |

For plan approval (`kind: 'switch_mode'`) the *labels* should be specific to the mode transition, not the generic verbs:

| `_meta.toMode` | Approve label | Decline label |
|---|---|---|
| `'execution'` (from `'plan'`) | "Execute plan" | "Keep planning" |
| `'plan'` (from any other) | "Switch to plan mode" | "Stay here" |
| (any other) | "Switch mode" | "Cancel" |

---

## 6. Progress / thinking messages

### 6.1 `_posthog/progress` → thinkingMessages.ts wiring

`_posthog/progress` notifications (§ 10.8 in `CLOUD_AGENTS_FRONTEND_SPEC.md`) are *structured backend progress events*. They group into one card on the client when emitted in the same turn.

Shape (lifted from current sandbox-side emitters):

```ts
interface PosthogProgressEvent {
    method: '_posthog/progress'
    params: {
        toolCallId?: string                  // when scoped to a tool call (e.g. summarize_sessions)
        sessionId: string
        runId: string
        kind: 'thinking' | 'tool_progress' | 'phase' | string
        text?: string                        // free-form copy ("Pondering the data…")
        payload?: Record<string, unknown>    // structured payload — driver of widgets
        timestamp: string
    }
}
```

Two consumers in the new architecture:

#### Consumer A — top-of-thread "PostHog AI is thinking" copy

Today `getThinkingMessageFromResponse` (in `posthog/frontend/src/scenes/max/utils/thinkingMessages.ts`) cycles through whimsical loading copy ("Pondering", "Hobsnobbing") while *no other tool chip is in flight*.

New behavior:

- `posthogAiThreadLogic` selector `currentThinkingCopy: string | null` returns:
  1. If the latest `_posthog/progress` event in the current turn has `kind === 'thinking'` and a non-empty `text`, return that text.
  2. Else, if `streamingActive` and no `in_progress` tool invocation, return a cycling whimsical message from `THINKING_MESSAGES` (the array stays — it's still a fallback).
  3. Else `null`.
- The thread renders `currentThinkingCopy` as a `<ReasoningAnswer animate>` (the same `ShimmeringContent`-wrapped component used today for in-progress reasoning).

The whimsical messages array doesn't need to move — keep it at `posthog-ai/utils/thinkingMessages.ts` (verbatim copy).

#### Consumer B — per-tool progress widgets (SessionSummarizationProgress etc.)

For tools with rich progress (e.g. `summarize_sessions`), the agent server emits multiple `_posthog/progress` notifications carrying structured `payload` over the lifetime of the tool call. The `toolCallId` ties them back to a specific invocation.

`toolCallsLogic.recordProgress` appends to `invocationsByCallId[toolCallId].progress[]`.

The renderer for these widgets reads `invocation.progress` directly:

```tsx
function SessionSummarizationProgressAdapter({ invocation }: { invocation: ToolInvocation }): JSX.Element {
    const updates: SessionSummarizationUpdate[] = useMemo(
        () => invocation.progress
            .map(p => p.params.payload)
            .filter(isSessionSummarizationUpdate),
        [invocation.progress]
    )
    return <SessionSummarizationProgress updates={updates} />
}
```

`isSessionSummarizationUpdate` is a runtime type guard — keep it simple and forgiving (matches `type === 'sessions_discovered' || type === 'progress'`, ignores everything else).

This means **no changes** to `SessionSummarizationProgress.tsx` itself — only an adapter wrapper.

### 6.2 SessionSummarizationProgress and similar adapters

Adapter modules in `posthog-ai/messages/adapters/`:

| Adapter | Source events | Target component |
|---|---|---|
| `SessionSummarizationProgressAdapter.tsx` | `invocation.progress` for `posthog-replay.summarize_sessions` | `messages/SessionSummarizationProgress.tsx` |
| `RecordingsCardAdapter.tsx` | `invocation.rawOutput.filters` (`RecordingUniversalFilters`) | `messages/UIPayloadAnswer.tsx → RecordingsWidget` |
| `ErrorTrackingCardAdapter.tsx` | `invocation.rawOutput` (`MaxErrorTrackingSearchResponse`) | `messages/UIPayloadAnswer.tsx → ErrorTrackingFiltersWidget` |
| `NotebookArtifactAdapter.tsx` | `invocation.content[]` + `invocation.rawOutput` | `messages/NotebookArtifactAnswer.tsx` |
| `VisualizationArtifactAdapter.tsx` | `invocation.content[]` + `invocation.rawOutput.query` | `messages/VisualizationArtifactAnswer.tsx` |
| `MultiQuestionFormRecapAdapter.tsx` | `invocation.rawInput.questions` + `invocation.rawOutput.answers` | `messages/MultiQuestionForm.tsx → MultiQuestionFormRecap` |

Each adapter is ~15 lines, isolated, easy to unit-test against fixtures captured from real `_posthog/progress` + `tool_call_update` streams.

---

## 7. The boundary events

### 7.1 `_posthog/turn_complete`

Marker that the current turn has ended (`CLOUD_AGENTS_FRONTEND_SPEC § 10.6`, payload `{ sessionId, stopReason }`).

When received:

- `posthogAiThreadLogic.actions.finalizeTurn({ stopReason })` fires.
- Effects:
  - Flip any in-flight `in_progress` invocations whose `tool_call_update` never arrived to a terminal status — `completed` if `stopReason === 'end_turn'`, `failed` otherwise. Without this, the UI can leave a spinning chip forever.
  - Trigger the "rating + retry + copy" `<SuccessActions>` block (today this happens via the `isFinal` prop in `Thread.tsx:618–658`).
  - Stop the whimsical thinking copy cycle (the selector in § 6.1.A naturally returns `null` when `streamingActive` becomes false).
  - Lock the assistant's last message — `status: 'completed'` — so subsequent rerenders don't re-stream.
  - Drain the queue (combine pending follow-ups and send — owned by `02_CORE.md` § 6).
  - Trigger feedback / ticket / multi-question-form-input affordances (today driven by `streamingActive` flip — see Thread.tsx:256–278).
- For per-tool consumers: `posthogAiThreadLogic` exposes `currentTurnEndedAt: string | null`. Renderers that want to *fade out* progress widgets after turn end can subscribe.

### 7.2 `_posthog/run_started`

Marker that a fresh run has begun (`{ sessionId, runId, taskId, agentVersion }`).

When received:

- `posthogAiThreadLogic.actions.markRunStarted({ runId, sessionId, taskId, agentVersion })`.
- Effects:
  - `streamingActive = true`.
  - `currentRunId = runId`.
  - Telemetry: emit `trace_id = runId` (this is the migration from per-turn `trace_id` — see `00_OVERVIEW.md` § 9.5).
  - Clear any cached "stale invocation" state from the previous run (call `toolCallsLogic.actions.clearInvocationsForRun(previousRunId)` for housekeeping — but keep invocations from prior runs of the *same task* visible in the thread).

### 7.3 Stop-reason handling

`stopReason` values to anticipate on `_posthog/turn_complete`:

| `stopReason` | UI state |
|---|---|
| `end_turn` | Normal completion. Show `<SuccessActions>` on the last AI message. |
| `error` | Show `<RetriableFailureActions>` (retry button). The last assistant block — if there is one — gets `status: 'failed'`. If no assistant message exists, append a synthetic `kind: 'failure'` thread item with the error text from `_posthog/error` (which arrives separately — see `02_CORE.md` § 5 for routing). |
| `cancelled` | Show "Cancelled" annotation; no retry button. Pending invocations flip to `failed`. |
| `tool_use` *(rare — interrupted before tool completion)* | Treat as `error` for now. |
| `max_tokens` | Treat as `end_turn` but surface a soft warning banner. |
| `queued` | Should not appear at `turn_complete` — log and ignore. |

---

## 8. File-by-file move plan

`scenes/max/` → `scenes/posthog-ai/` (per the overview).

### 8.1 Reused unchanged (verbatim copy)

| Source | Destination |
|---|---|
| `messages/MessageTemplate.tsx` | `posthog-ai/messages/MessageTemplate.tsx` |
| `messages/RecordingsFiltersSummary.tsx` | `posthog-ai/messages/RecordingsFiltersSummary.tsx` |
| `messages/ErrorTrackingFiltersSummary.tsx` | `posthog-ai/messages/ErrorTrackingFiltersSummary.tsx` |
| `messages/ErrorTrackingIssueCard.tsx` | `posthog-ai/messages/ErrorTrackingIssueCard.tsx` |
| `messages/maxErrorTrackingWidgetLogic.ts` | `posthog-ai/messages/postHogAiErrorTrackingWidgetLogic.ts` (rename only) |
| `messages/SessionSummarizationProgress.tsx` | `posthog-ai/messages/SessionSummarizationProgress.tsx` (the *renderer* — only the input wiring changes; see § 6.2 for the adapter) |
| `messages/MultiQuestionForm.tsx` (the `Recap`) | `posthog-ai/messages/MultiQuestionForm.tsx` |
| `MarkdownMessage.tsx` | `posthog-ai/MarkdownMessage.tsx` |
| `DangerousOperationApprovalCard.tsx` | `posthog-ai/DangerousOperationApprovalCard.tsx` (still reads from the renamed logic; props unchanged) |
| `approvalOperationUtils.ts` | `posthog-ai/approvalOperationUtils.ts` |
| `utils/thinkingMessages.ts` (the THINKING_MESSAGES array) | `posthog-ai/utils/thinkingMessages.ts` |
| `utils/markdownToTiptap.ts` | `posthog-ai/utils/markdownToTiptap.ts` |
| `max-constants.tsx` `ToolDefinition` + display formatters | `posthog-ai/tool-constants.tsx` (kept for chip text + icons; the new path drives `toolName`-based lookup) |
| `TraceIdContext.tsx` | `posthog-ai/TraceIdContext.tsx` |

### 8.2 Reused with a thin adapter

| Source | Adapter | Notes |
|---|---|---|
| `messages/VisualizationArtifactAnswer.tsx` | `messages/adapters/VisualizationArtifactAdapter.tsx` | The renderer keeps its props (`content`, `status`, `isEditingInsight`, `activeTabId`, `activeSceneId`). Adapter pulls these from a `ToolInvocation` (see § 3.1.6). |
| `messages/NotebookArtifactAnswer.tsx` | `messages/adapters/NotebookArtifactAdapter.tsx` | Renderer keeps `content`, `status`, `artifactId`. Adapter pulls these from a `ToolInvocation` (§ 3.1.5). |
| `messages/UIPayloadAnswer.tsx → RecordingsWidget` | `messages/adapters/RecordingsCardAdapter.tsx` | Renderer keeps `toolCallId`, `filters`. Adapter pulls `toolCallId` from invocation, `filters` from `rawOutput`. |
| `messages/UIPayloadAnswer.tsx → ErrorTrackingFiltersWidget` | `messages/adapters/ErrorTrackingCardAdapter.tsx` | Same idea. |
| `messages/UIPayloadAnswer.tsx → SummarizeSessionsWidget` | `messages/adapters/SessionSummaryLinkAdapter.tsx` | Just reads `rawOutput.session_group_summary_id` + `rawInput.summary_title`. |
| `messages/SessionSummarizationProgress.tsx` | `messages/adapters/SessionSummarizationProgressAdapter.tsx` | Reads `invocation.progress` (see § 6.2). |
| `messages/MultiQuestionForm.tsx → MultiQuestionFormRecap` | `messages/adapters/MultiQuestionFormRecapAdapter.tsx` | Reads `rawInput.questions`, `rawOutput.answers`, `rawOutput.status`. |
| `Thread.tsx → AssistantActionComponent` | extract to `posthog-ai/components/ToolCallChip.tsx` | The "chip with expandable substeps + optional widget" component. Reused for every chip-mode invocation. |
| `Thread.tsx → PlanningAnswer` | extract to `posthog-ai/messages/PlanningAnswer.tsx` | Used both in-thread (for `todo_write`-equivalent calls) and inside `PlanApprovalCard` (§ 5.2). |
| `Thread.tsx → MultiVisualizationAnswer` | `posthog-ai/messages/MultiVisualizationAnswer.tsx` | Today's input is `MultiVisualizationMessage` — a dedicated message type. In the new world this maps to *the assembly of multiple visualization invocations within a single turn*. Specifically: when a single agent turn produces N `posthog-data.read_data` invocations with `kind === 'insight'` + `execute: true`, group them into one `MultiVisualizationMessage`-equivalent. Owned by the selector in `posthogAiThreadLogic.threadGrouped`. |

### 8.3 Replaced

| Source | Replacement | Reason |
|---|---|---|
| `messages/UIPayloadAnswer.tsx` (top-level dispatcher) | `posthog-ai/Thread.tsx`'s renderer table + adapters | The whole `ui_payload`-detection logic is gone — replaced by `toolName`-keyed lookup (§ 3). |
| `Thread.tsx` (dispatch logic) | `posthog-ai/Thread.tsx` (new, but reuses extracted sub-components from § 8.2) | Different input model (`PostHogAiThreadItem[]` vs `ThreadMessage[]`). |
| `useMaxTool.ts` + `MaxTool.tsx` | `usePostHogAiTool.ts` (§ 4.4) | Different transport model. |
| The `getToolCallDescriptionAndWidget` function (`Thread.tsx:1652–1685`) | `posthog-ai/components/ToolCallChip.tsx`'s internal helpers | Keyed by `toolName` (MCP) now, not by `toolCall.name` (LangGraph). |
| `TOOL_DEFINITIONS[…].displayFormatter` (`max-constants.tsx`) | Same shape, keyed by MCP-qualified name | Keep the formatter style (it's nice). Just add `toolName: 'posthog-data.read_taxonomy'` → formatter mapping alongside the legacy `read_taxonomy` keys for the migration window. |

### 8.4 Deleted

| File | Reason |
|---|---|
| `messages/UIPayloadAnswer.tsx` (after callers migrate) | Top-level dispatcher; no consumers in the new model. |
| `MaxTool.tsx` | `@deprecated` in source today; just remove. |
| `useMaxTool.ts` | Replaced by `usePostHogAiTool.ts`. |
| `maxGlobalLogic.tsx` STATIC_TOOLS section | Static tools' identity now lives in the MCP server registry, not in the frontend. |
| `Thread.tsx` (the file at `scenes/max/Thread.tsx`) | Replaced by `posthog-ai/Thread.tsx`. |

(Deletion happens in the Phase-5 cleanup PR, not in Phase-3.)

---

## 9. Open questions

1. **MCP tool naming convention.** Do we go `posthog-data.read_taxonomy` (dotted) or `posthog_data__read_taxonomy` (underscored) on the wire? The mapping table assumes dotted; verify with `04_PROMPTS.md`. *Owner: AI.*

2. **`read_data` subtypes — keep as one MCP tool or split?** Today `read_data` is one LangGraph tool with `args.kind` discriminator and seven subtypes including `insight` (which can `execute: true` to materialize a query). Cleanest MCP design is seven separate tools (`read_billing`, `read_warehouse_schema`, `read_insight`, …) — but it bloats the tool count. Recommendation: keep as one and route in the renderer via `rawInput.kind`. *Owner: AI + frontend.*

3. **Client-side MCP infra (§ 4.1).** Need a green light from infra/backend on the new SSE frame `client_mcp_invoke` and command method `client_mcp_result`. Twig spec doesn't have these. *Owner: infra + AI.*

4. **`useMaxTool` semantic flip.** Migrating each call site requires understanding "given the args the agent sent, what's the right *result* shape to return". For pure side-effect tools (`filter_session_recordings` — applies filters, no real result), what do we return? Empty `{}`? `{ applied: true, filters }`? Standardize. *Owner: frontend.*

5. **Plan content backreference for `PlanApprovalCard`.** § 5.2 says we walk backwards from the `permission_request` to find the most recent `todo_write` invocation. This is fragile — if the agent calls other tools between the plan and the permission request, the chronological "most recent" might not be the right one. Cleaner: have the permission request's `_meta.planSnapshot` carry the plan directly. *Owner: AI (prompt) + 04_PROMPTS.md.*

6. **`MultiVisualizationMessage` equivalent.** Today this is a dedicated message type with a `commentary` field — the *agent* explicitly chose to render multiple visualizations together. In the new world this isn't a message type; it's a *grouping decision*. Do we always group N consecutive `read_data → insight (execute)` invocations within one turn, or is there a "render as group" signal from the agent? *Owner: AI + frontend.*

7. **Streaming `tool_call_update` semantics.** ACP says `tool_call_update.content` patches the prior content. Twig's `mergeToolCall` replaces wholesale when `patch.content` is non-empty (`cloudToolChanges.ts:53–59`). For diff/text streaming we might want to *append* instead. Pick one and document. Recommendation: replace-on-patch (Twig parity) — every MCP server is expected to send its full content on each update. *Owner: AI + frontend.*

8. **Generic fallback richness.** § 3.2 sketches `<GenericToolCallChip>` reusing today's `AssistantActionComponent`. Today's component is overloaded — should we split into a "lean" version for unknown tools (no JSON dump button, no SQL block) and keep the rich version for known tools? Decision deferred to implementation. *Owner: frontend.*

9. **Switching tools mid-stream.** When an MCP server crashes mid-call, the user-visible state is an invocation stuck at `status: 'in_progress'` with no further updates. We rely on `_posthog/turn_complete` to flip stuck invocations to `failed` (§ 7.3). Is that always emitted on crash? *Owner: AI + sandbox.*

10. **Filter `_posthog/console`** events from the rich-UI layer. Per `CLOUD_AGENTS_FRONTEND_SPEC § 17` these are dev-only (toggled by `debugLogsCloudRuns`). PostHog AI's equivalent toggle goes in user settings (or a feature flag). Until then, the watcher (`02_CORE.md`) silently drops them; this spec doesn't render them. Confirm. *Owner: AI + product.*

11. **`call_mcp_server` removal.** Today there's a `CallMCPServerTool` (LangGraph tool that wraps user-installed MCP servers as one meta-tool). In the new world the agent calls user MCPs directly; the meta-tool disappears. Verify no fronted code keys off `'call_mcp_server'` as a special identifier (the only mention is the entry in `TOOL_DEFINITIONS` with a generic chip; safe to drop). *Owner: AI.*

12. **`web_search` event surface.** Today this is a built-in Anthropic web search whose results stream as `updates: string[]` (each update is a Markdown-formatted link). In the ACP world, do these stream as `tool_call_update.content` blocks of type `text` with the same link format? Confirm wire shape before keeping the `displayFormatter` logic as-is. *Owner: AI.*

13. **`finalize_plan` shape.** Today a `FinalizePlanTool` exists in `ee/hogai/tools/finalize_plan/`. Tomorrow this becomes a `switch_mode` `requestPermission` (§ 5.2). Confirm the prompt-side change. *Owner: 04_PROMPTS.md.*

14. **Telemetry — `traceId` per tool call.** Today each tool call has a per-call `trace_id`. Tomorrow, a tool call's identity is `(runId, toolCallId)`. Confirm with LLM Analytics that this is the new dimension key. *Owner: AI + LLM Analytics.*

15. **Tool icons.** `TOOL_DEFINITIONS[*].icon` is keyed by today's identifier. New MCP-qualified names need an icon lookup (e.g. `posthog-data.read_taxonomy` → `iconForType('data_warehouse')`). Plan: add a parallel `MCP_TOOL_ICONS: Record<string, JSX.Element>` map alongside `TOOL_DEFINITIONS` and migrate over time, falling back to `<IconWrench />`. *Owner: frontend.*
