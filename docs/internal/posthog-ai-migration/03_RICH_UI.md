# 03 — Rich UI (MCP tool-name dispatch)

This spec covers the frontend slice of the migration. The premise (locked by `00_OVERVIEW.md`): the chat scene under `frontend/src/scenes/max/` stays. No new scene, no new dispatcher framework, no callback channel from agent to scene. The only structural change is a tool-name → renderer registry plus a handful of adapter wrappers around the renderers we already have.

You are also reading this because the wire format is now ACP frames carried inside `StoredLogEntry` envelopes (see `02_CORE.md` § 4 — sketched in `00_OVERVIEW.md` § 5 / § 7 until the full doc lands). What flows in is:

- `session/update` notifications with `params.update.sessionUpdate === 'tool_call' | 'tool_call_update'`. The frontend dispatches off these, mirroring `Twig/apps/code/.../cloudToolChanges.ts`.
- `permission_request` events the SSE relay hoists out of upstream agent-server JSON-RPC requests.
- `_posthog/progress`, `_posthog/run_started`, `_posthog/turn_complete` for thinking messages, run boundaries, stop reasons.
- `session/update` with `sessionUpdate === 'agent_message_chunk' | 'agent_thought_chunk'` for streamed assistant text (kept folded into `AssistantMessage` shape on the wire — frontend keeps treating them as today).

The deprecated `useMaxTool` / `MaxTool` system goes away. Only the static MCP tool set is callable. Scenes contribute `AttachedContext` items (see `01_CONTEXT.md`) and may subscribe read-only to `maxThreadLogic`. They cannot expose callbacks.

---

## 1. Today: how rendering works

### 1.1 Thread.tsx dispatch path

`frontend/src/scenes/max/Thread.tsx` consumes `threadGrouped: ThreadMessage[]` from `maxThreadLogic`. Each `ThreadMessage` is one of:

- `HumanMessage` — `MarkdownMessage` (or slash-command pill).
- `AssistantMessage` — `TextAnswer` (markdown), plus reasoning blocks via `getThinkingMessageFromResponse()`, plus `ToolCallsAnswer` rendered from `message.tool_calls[]`. Each tool call dispatches into `AssistantActionComponent` with description / icon / widget computed by `getToolCallDescriptionAndWidget()` against `TOOL_DEFINITIONS`.
- `AssistantToolCallMessage` — only rendered when `message.ui_payload` has a key in `RENDERABLE_UI_PAYLOAD_TOOLS` or matches `isDangerousOperationResponse()`. Dispatch goes through `UIPayloadAnswer` (kind-based — see § 1.3).
- `ArtifactMessage` — branches on artifact content type: `VisualizationArtifactAnswer` or `NotebookArtifactAnswer`.
- `MultiVisualizationMessage` — `MultiVisualizationAnswer`.
- `FailureMessage` — error pill.

`Thread.tsx` also fishes pending-approval cards out of `pendingApprovalsData` by `tool_call_id`, rendering `DangerousOperationApprovalCard` next to the assistant message that originated the call.

`SandboxActivityPanel` is a transitional element (driven by `PHAI_SANDBOX_MODE` flag and the `sandboxEntries: LogEntry[]` selector). It collapses raw sandbox tool/console traffic into a debug panel. The MCP-tool-call work supersedes it for tool entries — once the registry handles real cards, this panel is deleted.

### 1.2 messages/\* renderer catalog

| File                               | Component                      | Today's props                                                                                                                     | What it visualizes                                                                                                                                     |
| ---------------------------------- | ------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `MessageTemplate.tsx`              | `MessageTemplate`              | `type: 'human' \| 'ai'`, `boxClassName`, `wrapperClassName`, `action`, children                                                   | Bubble shell. Used by every other renderer. Reused untouched.                                                                                          |
| `VisualizationArtifactAnswer.tsx`  | `VisualizationArtifactAnswer`  | `message: ArtifactMessage`, `content: VisualizationArtifactContent`, `status`, `isEditingInsight`, `activeTabId`, `activeSceneId` | A finished insight artifact (query + viz). Reads from `content.query`, source = `Insight` vs inline.                                                   |
| `NotebookArtifactAnswer.tsx`       | `NotebookArtifactAnswer`       | `content: NotebookArtifactContent`, `status`, `artifactId`                                                                        | Multi-block notebook artifact (markdown / visualization / session_replay / loading / error). Save-to-notebook button.                                  |
| `UIPayloadAnswer.tsx`              | `UIPayloadAnswer`              | `toolCallId`, `toolName`, `toolPayload: any`                                                                                      | Kind-based dispatcher. See § 1.3.                                                                                                                      |
| `UIPayloadAnswer.tsx`              | `RecordingsWidget`             | `toolCallId`, `filters: RecordingUniversalFilters`                                                                                | Embedded recordings playlist for a `search_session_recordings` / `filter_session_recordings` result.                                                   |
| `UIPayloadAnswer.tsx`              | `ErrorTrackingFiltersWidget`   | `toolCallId`, `filters: MaxErrorTrackingSearchResponse \| null`                                                                   | Embedded issue list driven by `maxErrorTrackingWidgetLogic`. Optionally pushes filters into the error-tracking scene if active.                        |
| `UIPayloadAnswer.tsx`              | `SummarizeSessionsWidget`      | `payload: { session_group_summary_id?, title? }`, `title?`                                                                        | Single "Open analysis of sessions" button — rendered next to the in-progress `summarize_sessions` tool card.                                           |
| `ErrorTrackingFiltersSummary.tsx`  | `ErrorTrackingFiltersSummary`  | `filters: MaxErrorTrackingSearchResponse`                                                                                         | Filter chip row for an issue search.                                                                                                                   |
| `ErrorTrackingIssueCard.tsx`       | `ErrorTrackingIssueCard`       | `issue: MaxErrorTrackingIssuePreview`, `showUserCount?`                                                                           | Single-row issue preview.                                                                                                                              |
| `RecordingsFiltersSummary.tsx`     | `RecordingsFiltersSummary`     | `filters: RecordingUniversalFilters`                                                                                              | Filter chip row for a recording search.                                                                                                                |
| `MultiQuestionForm.tsx`            | `MultiQuestionFormRecap`       | `form: MultiQuestionForm`, `savedAnswers?`, `formStatus?`                                                                         | Read-only recap of a previously-submitted in-chat form. The live form lives in the input area, not the thread.                                         |
| `SessionSummarizationProgress.tsx` | `SessionSummarizationProgress` | `updates: SessionSummarizationUpdate[]`                                                                                           | Live progress for `summarize_sessions` — derives per-session status, phase, ETA, patterns from a stream of `progress` / `sessions_discovered` updates. |
| `maxErrorTrackingWidgetLogic.ts`   | (kea logic)                    | `toolCallId`, `filters`                                                                                                           | Paginates issues for `ErrorTrackingFiltersWidget`.                                                                                                     |

Outside `messages/`: `MarkdownMessage.tsx`, `DangerousOperationApprovalCard.tsx`, `approvalOperationUtils.ts`. All reused untouched.

### 1.3 UIPayloadAnswer's kind-based dispatch

Today every `AssistantToolCallMessage` arrives with a `ui_payload: Record<toolName, payload>` synthesized server-side. `Thread.tsx` flattens the first key, `UIPayloadAnswer` switches on `toolName`:

- `search_session_recordings` → `RecordingsWidget`.
- `search_error_tracking_issues` → `ErrorTrackingFiltersWidget`.
- `summarize_sessions` → `SummarizeSessionsWidget` (rendered outside the accordion in `Thread.tsx`).
- `create_form` → no widget; the form is handled in input area.
- Anything matching `isDangerousOperationResponse()` → `DangerousOperationApprovalCard`.

That's it. Most tools have no `ui_payload` entry and only ever render through the description text in `AssistantActionComponent`. `RENDERABLE_UI_PAYLOAD_TOOLS` is the canonical allowlist.

### 1.4 The deprecated useMaxTool model

`useMaxTool` (`useMaxTool.ts`) and the `MaxTool` wrapper component (`MaxTool.tsx`) let scenes call `registerTool(...)` on `maxGlobalLogic.toolMap`. The agent could read the registered tools' `context`/`suggestions` (compiled into a system prompt by the LangGraph runtime) and invoke `callback(toolOutput, conversationId)` on the scene's side when the tool completed. That whole loop is gone — the sandbox runtime can't reach back into a scene. Only static MCP tools exist after this migration.

`TOOL_DEFINITIONS` (`max-constants.tsx`) maps tool names to display metadata (icon, name, `displayFormatter`, optional `subtools`). It lives alongside `ToolDefinition` / `ToolRegistration` types and the `registerTool` / `deregisterTool` reducers in `maxGlobalLogic`. All of it goes — § 8.

---

## 2. Tomorrow: tool-name dispatch

### 2.1 Incoming shapes — sandboxStreamLogic output

The SSE relay (`02_CORE.md` § 4) passes ACP frames through raw, wrapped in a `StoredLogEntry` envelope. The merging from `tool_call` + N × `tool_call_update` into one coherent record happens **client-side** in `sandboxStreamLogic.ts` (`02_CORE.md` § 6). That module exposes `ToolInvocation` records — the input to this spec's registry — keyed by `toolCallId`:

```ts
interface ToolInvocation {
  toolCallId: string
  serverName: string // e.g. 'posthog-data'
  toolName: string // e.g. 'create_insight'
  qualifiedName: string // `${serverName}.${toolName}` — registry key
  input: Record<string, unknown> // rawInput at tool_call
  output?: unknown // rawOutput on the final tool_call_update
  progress?: unknown // partial result from intermediate updates
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
  title?: string // ACP toolCall.title
  kind?: string // ACP toolCall.kind (e.g. 'switch_mode' for plan approvals)
  locations?: { path: string; line?: number }[]
  contentBlocks: unknown[] // accumulated ACP `content[]` from updates
}

interface PermissionRequestRecord {
  requestId: string
  toolCallId: string // links back to the ToolInvocation
  options: PermissionOption[] // {optionId, name, kind} where kind ∈ allow_once|allow_always|reject|reject_with_feedback
  title?: string
  description?: string
  rawToolCall: ToolInvocation // the gated tool call, for preview/payload rendering
}
```

The registry described below dispatches on `ToolInvocation.qualifiedName`. The discriminator pattern mirrors `Twig/apps/code/src/renderer/features/task-detail/utils/cloudToolChanges.ts` — `sandboxStreamLogic` ports its walk: read `params.update.sessionUpdate`, key by `params.update.toolCallId`, merge subsequent `tool_call_update`s into the same record. **All merging is frontend-side**; the backend relay never reads tool semantics.

> **Why frontend merge:** the relay stays a thin passthrough that knows nothing about tools. Adding a new MCP tool requires zero backend change beyond exposing it as an MCP server — the frontend registry and the (optional) adapter cover the rest. See `00_OVERVIEW.md` § 2 and `02_CORE.md` § 6 for the rationale.

### 2.2 The qualified-name discriminator

The registry key is `toolName` as it appears on the wire — the full MCP qualified name `<server_name>.<tool_name>`, e.g. `posthog-data.read_taxonomy`, `posthog-data.execute_sql`, `posthog-notebook.create_notebook`. Backend MCP server slugs are owned by `04_PROMPTS.md` § 5; the registry must match exactly what those servers register. Built-in agent tools that aren't MCP (e.g. Claude's `web_search_20250305`) ship without a server prefix and are keyed directly by name (`web_search`).

Bare-name fallback: the registry also matches against the unqualified `tool_name` so we don't break if backend renames a server. The lookup is `registry[toolName] ?? registry[toolName.split('.').at(-1)!] ?? FallbackRenderer`.

### 2.3 Thread.tsx additive case

The dispatch is purely additive — drop a new branch into the `Message` IIFE in `Thread.tsx`, just above the `isMultiVisualizationMessage` branch. Sketch:

```tsx
} else if (isMcpToolCallMessage(message)) {
    const entry = lookupMcpToolRenderer(message.toolName)
    return <entry.Renderer key={key} message={message} isLastInGroup={isLastInGroup} />
} else if (isPermissionRequestMessage(message)) {
    return <PermissionRequestRouter key={key} message={message} />
} else if (isMultiVisualizationMessage(message)) {
    // …existing…
}
```

`isMcpToolCallMessage` / `isPermissionRequestMessage` go into `frontend/src/scenes/max/utils.ts` alongside the existing `isAssistantMessage` etc. Lookups are pure functions exported from `mcpToolRegistry.tsx`.

No other change in `Thread.tsx` is required for the core path. The existing `AssistantToolCallMessage` branch and `ToolCallsAnswer` stay during the soak — they're the LangGraph code path. Once `agent_runtime === 'sandbox'` becomes the default, those become dead code and can be deleted.

The `SandboxActivityPanel` in Thread.tsx is removed at the same time — its function is subsumed by individual tool cards (with the fallback renderer covering unknown tools).

### 2.4 Streaming + status mapping

ACP carries `tool_call.status: 'pending' | 'in_progress' | 'completed' | 'failed'` (`pending` before any progress, `in_progress` while running, terminal at the end). The renderer receives the same `status` field on every render and is responsible for showing the right state. Convention for all renderers:

| Status        | Visual                                                                                              |
| ------------- | --------------------------------------------------------------------------------------------------- |
| `pending`     | Card placeholder, muted text, no spinner yet.                                                       |
| `in_progress` | Shimmering header + spinner; partial `content` shown if useful (e.g. session list as it discovers). |
| `completed`   | Final widget; check icon on header; expandable raw output.                                          |
| `failed`      | Red header; `error.message` shown verbatim; raw output if available.                                |

Renderers that already have streaming behavior (`NotebookArtifactAnswer` shows skeleton + `Generating…`, `SessionSummarizationProgress` derives from progress updates) keep doing what they do — the renderer-adapter feeds them the same shape they expect via the input/output extractor.

---

## 3. The mcpToolRegistry

New file: `frontend/src/scenes/max/mcpToolRegistry.tsx`.

### 3.1 Shape

```ts
import type { ComponentType } from 'react'
import type { McpToolCallMessage } from './maxTypes'

export interface McpToolRendererProps {
  message: McpToolCallMessage
  isLastInGroup: boolean
}

export interface McpToolRegistryEntry {
  /** Full qualified MCP tool name, e.g. "posthog-data.execute_sql", "web_search". */
  toolName: string
  /** Display name / icon for fallback rendering and for the tool-call header line. */
  displayName: string
  icon: JSX.Element
  Renderer: ComponentType<McpToolRendererProps>
  /**
   * If true, the registry will also match the unqualified tail of `toolName` (everything after the last dot).
   * Used to bridge server-renames during rollout.
   */
  matchUnqualified?: boolean
}

export interface McpToolRegistry {
  register(entry: McpToolRegistryEntry): void
  lookup(toolName: string): McpToolRegistryEntry | null
}
```

`lookup` returns `null` when nothing matches; `Thread.tsx` falls back to the generic renderer in that case (§ 3.4).

### 3.2 Registration

Single module-level `mcpToolRegistry` instance. All entries registered at module load — no dynamic registration, no hooks, no scene callbacks:

```ts
// mcpToolRegistry.tsx
class MapBackedRegistry implements McpToolRegistry {
  /* ... */
}
export const mcpToolRegistry = new MapBackedRegistry()

mcpToolRegistry.register({
  toolName: 'posthog-data.execute_sql',
  displayName: 'Execute SQL',
  icon: iconForType('insight/hog'),
  Renderer: ExecuteSqlRenderer,
  matchUnqualified: true,
})
// ...one block per tool, grouped by MCP server with a header comment.
```

The static MCP tool universe is bounded by `04_PROMPTS.md` § 5 + Claude built-ins; the registry has one entry per row in the § 4 table. Locality matters more than abstraction here — keep all registrations in this one file so the surface is greppable.

### 3.3 Adapter pattern — worked examples

Adapters are thin wrappers (5–15 lines) that extract props from `message.rawInput` / `message.content` / `message.rawOutput` and call the existing component. They live next to the registry in a `frontend/src/scenes/max/messages/adapters/` directory, one file per MCP tool.

**Example A — Visualization artifact adapter** (covers `posthog-data.create_insight`):

```tsx
// messages/adapters/CreateInsightAdapter.tsx
import { VisualizationArtifactAnswer } from '../VisualizationArtifactAnswer'
import type { McpToolRendererProps } from '../../mcpToolRegistry'
import { extractVisualizationArtifact } from './extractors'

export function CreateInsightAdapter({ message }: McpToolRendererProps): JSX.Element | null {
  const artifact = extractVisualizationArtifact(message)
  if (!artifact) {
    return <PendingToolCard message={message} />
  }
  return (
    <VisualizationArtifactAnswer
      message={artifact.envelope}
      content={artifact.content}
      status={message.status === 'completed' ? 'completed' : 'streaming'}
      isEditingInsight={false}
      activeTabId={null}
      activeSceneId={null}
    />
  )
}
```

`extractVisualizationArtifact(message)` pulls the artifact id and `VisualizationArtifactContent` out of `message.rawOutput` (the MCP tool returns it directly; backend MCP server is responsible for matching the existing shape). `isEditingInsight` / `activeTabId` / `activeSceneId` collapse to `false`/`null` because the contextual-edit flow is dead — only the static "create new insight" path remains. (Open question § 10: how does the user re-target an existing insight from chat? Likely a separate MCP tool `posthog-data.edit_insight` that ships the same artifact content with `source: ArtifactSource.Insight` and the `artifact_id`. Same adapter, same component.)

**Example B — Notebook adapter** (covers `posthog-notebook.create_notebook`):

```tsx
export function CreateNotebookAdapter({ message }: McpToolRendererProps): JSX.Element | null {
  const content = extractNotebookContent(message)
  if (!content) {
    return <PendingToolCard message={message} />
  }
  return <NotebookArtifactAnswer content={content} status={mapStatus(message.status)} artifactId={message.id} />
}
```

Notebook tool emits blocks as it goes (the backend MCP server should stream them through ACP `tool_call_update.content` as text content with a structured payload, or via a side-channel `_posthog/notebook_block` notification — see open question § 10). For phase 3 we can ship batch-only first (blocks arrive on `completed`) and add streaming later — `NotebookArtifactAnswer` already handles the `isStreaming && !hasContent` case.

**Example C — Session summarization adapter** (covers `posthog-data.summarize_sessions`):

`SessionSummarizationProgress` expects `updates: SessionSummarizationUpdate[]`. The adapter accumulates the structured updates the backend MCP server emits as text-content frames in `tool_call_update.content` (mirroring how `summarize_sessions.updates` work today):

```tsx
export function SummarizeSessionsAdapter({ message }: McpToolRendererProps): JSX.Element {
  const updates = useMemo(() => parseSessionSummarizationUpdates(message.content), [message.content])
  const completedPayload =
    message.status === 'completed'
      ? (message.rawOutput as { session_group_summary_id?: string; title?: string } | undefined)
      : undefined
  return (
    <MessageTemplate type="ai">
      <SessionSummarizationProgress updates={updates} />
      {completedPayload?.session_group_summary_id && (
        <SummarizeSessionsWidget payload={completedPayload} title={completedPayload?.title} />
      )}
    </MessageTemplate>
  )
}
```

`parseSessionSummarizationUpdates(content)` walks `content` looking for `{ type: 'text', text }` frames whose JSON parse matches `{ type: 'sessions_discovered' | 'progress', … }`. The adapter owns the streaming shape so `SessionSummarizationProgress` stays unchanged.

The same pattern applies to every other renderer — adapter does the shape mapping; component stays the way it is.

### 3.4 Fallback renderer

When `mcpToolRegistry.lookup(toolName)` returns `null` (user-installed MCP, unknown server, etc.), `Thread.tsx` falls back to `FallbackMcpToolRenderer` defined in `UIPayloadAnswer.tsx` (repurposed as the registry's spillover home — the kind-based dispatcher inside it is gone, replaced by this single fallback). It renders a generic tool card:

- Header line: `<icon> <message.title || message.toolName>` plus status badge.
- Expandable accordion: `rawInput` JSON, then `content[]` (text frames pretty-printed; non-text frames as JSON), then `rawOutput` if present.
- For `failed` status, top-level red message with `error.message`.

This is the catch-all that lets us ship the registry incrementally — every backend MCP tool that's enabled but not yet wired through an adapter still renders something sensible.

The `RecordingsWidget`, `ErrorTrackingFiltersWidget`, `SummarizeSessionsWidget` exports stay (`Thread.tsx` and adapters import them), but `UIPayloadAnswer` itself shrinks to just `FallbackMcpToolRenderer` + those widget exports.

---

## 4. Tool → renderer mapping table

Every backend tool from `ee/hogai/chat_agent/toolkit.py` (`DEFAULT_TOOLS` + `TASK_TOOLS` + `TaskTool` + Claude built-ins) gets a row. The `MCP qualified name` column is the working name; final slugs come from `04_PROMPTS.md` § 5. Where a tool's MCP-side shape isn't pinned down yet, the row is marked **TODO — confirm**.

| MCP qualified name                                            | Frontend renderer                                                                             | Input extractor (`rawInput`)               | Output extractor (`rawOutput` / `content`)                                                                                   | Notes                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| ------------------------------------------------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `posthog-data.read_taxonomy`                                  | Fallback card                                                                                 | `kind`, `entity`                           | `content[]` text frames                                                                                                      | Description-only today; no widget needed. Header text via `displayName`.                                                                                                                                                                                                                                                                                                                                                                                  |
| `posthog-data.read_data` (and per-sub-kind siblings)          | Fallback card                                                                                 | `query: { kind, … }`                       | `content[]` text frames; large tabular results truncated                                                                     | The existing PostHog MCP server already exposes each `read_data.subtools` entry as a first-class tool (`read_data_warehouse_schema`, `read_actions`, etc.) — registry mirrors that layout, one row per first-class tool. The per-tool description carries the human label (`Read billing data`, etc.). No flattening, no in-adapter `kind` dispatch.                                                                                                       |
| `posthog-data.list_data`                                      | Fallback card                                                                                 | `kind`, `offset`                           | List excerpts in `content[]`                                                                                                 | Description shows `Listed surveys (page 2)` etc. Reuse the existing string-formatting helper.                                                                                                                                                                                                                                                                                                                                                             |
| `posthog-data.search` (and per-sub-kind siblings)             | Fallback card                                                                                 | `kind`, `query`                            | List excerpts in `content[]`                                                                                                 | Same shape as `list_data` row above — registry mirrors the existing MCP server's first-class layout per sub-kind. No flattening.                                                                                                                                                                                                                                                                                                                          |
| `posthog-data.execute_sql`                                    | `ExecuteSqlAdapter` (new)                                                                     | `query: string`                            | Either a `VisualizationArtifactContent` (when results are tabular) or a HogQL result blob in `content[]`                     | Renders a code snippet of the input query plus the result; for now delegate the result rendering to `Query` with a `HogQLQuery` source when the output indicates a runnable query. Equivalent to the inline `executedSQLQuery` path in today's `AssistantActionComponent`.                                                                                                                                                                                |
| `posthog-data.create_insight` / `posthog-data.edit_insight`   | `CreateInsightAdapter` (new) → `VisualizationArtifactAnswer`                                  | `query` shape (`artifact_id` on edit)      | `rawOutput` → `VisualizationArtifactContent` (`{ query, source, artifact_id? }`)                                             | See § 3.3 Example A. Two sibling tools mirror the existing PostHog MCP naming (`query-*` for ephemeral / read-style + the `insight-*` write variants — exact slugs owned by the MCP server). One adapter handles both; the `artifact_id` discriminates create vs edit at render time.                                                                                                                                                                     |
| `posthog-data.upsert_dashboard`                               | `UpsertDashboardAdapter` (new)                                                                | `action`, `dashboard` payload              | `rawOutput` → `{ dashboard_id, url? }`                                                                                       | **TODO — confirm** whether the result is rendered as a "View dashboard" CTA or a full embedded dashboard preview. Today's UI only shows a status line — keep that for v1.                                                                                                                                                                                                                                                                                 |
| `posthog-data.create_form`                                    | **Deferred** — see [`TODO.md`](./TODO.md) "MultiQuestionForm answer channel"                  | `questions`                                | n/a                                                                                                                          | The Claude Code SDK may ship a built-in form / structured-question tool; if it does we map onto it and reuse the existing input-area form UI + `MultiQuestionFormRecap`. If not, the `create_form` tool is **deprecated for v1** of the sandbox runtime and clarification-via-form is dropped — the agent asks clarifying questions in plain text. Tracked in `TODO.md`.                                                                                   |
| `posthog-data.search_session_recordings`                      | `SearchSessionRecordingsAdapter` (new) → `RecordingsWidget`                                   | `query`/`filters`                          | `rawOutput.filters: RecordingUniversalFilters`                                                                               | One-line adapter.                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `posthog-data.filter_session_recordings`                      | `FilterSessionRecordingsAdapter` (new) → `RecordingsWidget`                                   | `recordings_filters`                       | `rawOutput.filters`                                                                                                          | Same renderer, different display text.                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `posthog-data.summarize_sessions`                             | `SummarizeSessionsAdapter` (new) → `SessionSummarizationProgress` + `SummarizeSessionsWidget` | `session_ids?`, `summary_title?`           | `content[]` streamed `SessionSummarizationUpdate` JSON frames; `rawOutput.{ session_group_summary_id, title }` on completion | See § 3.3 Example C.                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `posthog-data.search_error_tracking_issues`                   | `SearchErrorTrackingIssuesAdapter` (new) → `ErrorTrackingFiltersWidget`                       | `search_query`, `status`, etc.             | `rawOutput: MaxErrorTrackingSearchResponse` (existing schema)                                                                | One-liner.                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `posthog-data.filter_error_tracking_issues`                   | Same renderer as above                                                                        | `filters`                                  | `rawOutput: MaxErrorTrackingSearchResponse`                                                                                  | Reuses `ErrorTrackingFiltersWidget`.                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `posthog-data.find_error_tracking_impactful_issue_event_list` | Fallback card                                                                                 | `events`, `period`                         | List                                                                                                                         | **TODO — confirm** whether a custom widget is worthwhile vs. text. Probably stay on fallback until product validates.                                                                                                                                                                                                                                                                                                                                     |
| `posthog-data.experiment_results_summary`                     | Fallback card                                                                                 | `experiment_id`                            | Summary text in `content[]`                                                                                                  | Today text-only.                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `posthog-data.experiment_session_replays_summary`             | `SessionSummarizationAdapter` variant or fallback                                             | `experiment_id`, `variant`                 | Mirrors `summarize_sessions`                                                                                                 | **TODO — confirm** if backend reuses the same progress shape; if yes reuse the adapter; otherwise fallback.                                                                                                                                                                                                                                                                                                                                               |
| `posthog-data.analyze_user_interviews`                        | Fallback card                                                                                 | `topic_id`                                 | Summary text + extracted themes in `content[]`                                                                               | Could later get a themes widget.                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `posthog-data.create_user_interview_topic`                    | Fallback card                                                                                 | `name`, `questions`                        | `rawOutput.topic_id`, `rawOutput.url`                                                                                        | "Open in user interviews" CTA via fallback `rawOutput.url`.                                                                                                                                                                                                                                                                                                                                                                                               |
| ~~`posthog-data.fix_hogql_query`~~                            | **Dropped.** Not exposed as a tool in the sandbox runtime.                                    | n/a                                        | n/a                                                                                                                          | The "fix this query" affordance lives in the insight editor UI — clicking it opens a Max conversation pre-filled with a prompt like "Fix this HogQL query: ...". No backend tool. See [`TODO.md`](./TODO.md) "Insight editor → Max 'fix this query' trigger" for the UI wiring.                                                                                                                                                                           |
| `posthog-data.filter_revenue_analytics`                       | Fallback card                                                                                 | `filters`                                  | `rawOutput.url`                                                                                                              | "Open revenue analytics" CTA.                                                                                                                                                                                                                                                                                                                                                                                                                             |
| `posthog-data.filter_web_analytics`                           | Fallback card                                                                                 | `filters`                                  | `rawOutput.url`                                                                                                              | "Open web analytics" CTA.                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| `posthog-data.web_analytics_doctor`                           | Fallback card                                                                                 | n/a                                        | Diagnostic text in `content[]`                                                                                               | Text-only.                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `posthog-data.diagnose_proxy`                                 | Fallback card                                                                                 | n/a                                        | Diagnostic text in `content[]`                                                                                               | Text-only.                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `posthog-data.search_llm_traces`                              | Fallback card                                                                                 | `query`, `period`                          | List + `rawOutput.url`                                                                                                       | "Open in LLM analytics" CTA.                                                                                                                                                                                                                                                                                                                                                                                                                              |
| `posthog-data.run_hog_eval_test`                              | Fallback card                                                                                 | `evaluation_id`, `event_id`                | Pass/fail + reasoning in `content[]`                                                                                         | Text-only.                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `posthog-data.upsert_alert`                                   | Fallback card                                                                                 | `action`, `alert`                          | `rawOutput.alert_id`                                                                                                         | "View alert" CTA.                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `posthog-feature-flags.create_feature_flag`                   | Fallback card                                                                                 | `key`, `filters`                           | `rawOutput.flag_id`, `rawOutput.url`                                                                                         | "Open flag" CTA.                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `posthog-feature-flags.create_experiment`                     | Fallback card                                                                                 | `name`, `flag_key`, etc.                   | `rawOutput.experiment_id`, `rawOutput.url`                                                                                   | "Open experiment" CTA.                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `posthog-surveys.create_survey`                               | Fallback card                                                                                 | `template`, `questions`                    | `rawOutput.survey_id`, `rawOutput.url`                                                                                       | "Open survey" CTA.                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `posthog-surveys.edit_survey`                                 | Fallback card                                                                                 | `survey_id`, `patch`                       | `rawOutput.survey_id`, `rawOutput.url`                                                                                       | "Open survey" CTA.                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `posthog-surveys.analyze_survey_responses`                    | Fallback card                                                                                 | `survey_id`                                | Themes in `content[]`                                                                                                        | Same shape as user-interview analysis.                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `posthog-notebook.create_notebook`                            | `CreateNotebookAdapter` → `NotebookArtifactAnswer`                                            | `title`, `prompt`                          | `rawOutput.blocks: DocumentBlock[]`, `rawOutput.title`, `rawOutput.artifact_id`                                              | See § 3.3 Example B. **v1 renders the whole notebook on tool completion — no block-by-block streaming.** Streaming is deferred per [`TODO.md`](./TODO.md) "Notebook block streaming". The component still supports streaming if `blocks` arrive incrementally, so the future switch is wire-format only.                                                                                                                                                  |
| `posthog-notebook.create_message_template`                    | Fallback card                                                                                 | `name`, `prompt`                           | `rawOutput.template_id`                                                                                                      | Text-only for now.                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| `posthog-tasks.todo_write`                                    | `TodoWriteAdapter` (new) → `PlanningAnswer` (extract from `Thread.tsx`)                       | `todos: { content, status, activeForm }[]` | n/a                                                                                                                          | `PlanningAnswer` already exists in `Thread.tsx`. Lift it to its own file (`messages/PlanningAnswer.tsx`) so the adapter can import it cleanly.                                                                                                                                                                                                                                                                                                            |
| `posthog-tasks.task`                                          | Fallback card with sub-task spinner                                                           | `title`, `prompt`                          | Streamed updates in `content[]`; `rawOutput.result` on completion                                                            | **TODO — confirm**; equivalent of today's `task` tool. Keep on fallback until product validates a dedicated card.                                                                                                                                                                                                                                                                                                                                         |
| `posthog-tasks.create_task`                                   | Fallback card                                                                                 | `title`, `repository`, `prompt`            | `rawOutput.task_id`, `rawOutput.url`                                                                                         | "Open task" CTA. (PHAI_TASKS feature.)                                                                                                                                                                                                                                                                                                                                                                                                                    |
| `posthog-tasks.run_task`                                      | Fallback card                                                                                 | `task_id`                                  | `rawOutput.run_id`, `rawOutput.url`                                                                                          | "Open task run" CTA.                                                                                                                                                                                                                                                                                                                                                                                                                                      |
| `posthog-tasks.get_task_run`                                  | Fallback card                                                                                 | `run_id`                                   | Status text in `content[]`                                                                                                   | Text-only.                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `posthog-tasks.get_task_run_logs`                             | Fallback card                                                                                 | `run_id`                                   | Logs in `content[]`                                                                                                          | Text-only. Truncate aggressively.                                                                                                                                                                                                                                                                                                                                                                                                                         |
| `posthog-tasks.list_tasks`                                    | Fallback card                                                                                 | `repository?`, `status?`                   | List in `content[]`                                                                                                          | Text-only.                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `posthog-tasks.list_task_runs`                                | Fallback card                                                                                 | `task_id`                                  | List in `content[]`                                                                                                          | Text-only.                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `posthog-tasks.list_repositories`                             | Fallback card                                                                                 | n/a                                        | List                                                                                                                         | Text-only.                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `posthog-transformations.create_hog_function_filters`         | Fallback card                                                                                 | `filters`                                  | `rawOutput.url`                                                                                                              | "Open transformation" CTA.                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `posthog-transformations.create_hog_transformation_function`  | Fallback card                                                                                 | `name`, `code`                             | `rawOutput.url`                                                                                                              | "Open transformation" CTA.                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `posthog-transformations.create_hog_function_inputs`          | Fallback card                                                                                 | `inputs`                                   | `rawOutput.url`                                                                                                              | "Open transformation" CTA.                                                                                                                                                                                                                                                                                                                                                                                                                                |
| `web_search` (Claude built-in)                                | `WebSearchAdapter` (new)                                                                      | `query`                                    | `rawOutput.results: { title, url }[]`                                                                                        | Same display as today's `server_tool_use` block — header `Searched the web for **<query>**` plus a list of titles linking out.                                                                                                                                                                                                                                                                                                                            |
| ~~`switch_mode`~~                                             | **Dropped.** Tool no longer exists per `04_PROMPTS.md` § 4.                                   | n/a                                        | n/a                                                                                                                          | Stale conversations that reference it fall back to the generic card.                                                                                                                                                                                                                                                                                                                                                                                      |
| `finalize_plan` (built-in)                                    | Fallback card                                                                                 | n/a                                        | n/a                                                                                                                          | One-line status.                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| `manage_memories` (built-in, deprecated for sandbox)          | Hidden                                                                                        | n/a                                        | n/a                                                                                                                          | Tool isn't exposed in sandbox runtime. If a stale conversation references it, render as fallback.                                                                                                                                                                                                                                                                                                                                                         |
| `call_mcp_server` (built-in proxy, soft-deprecated)           | Hidden                                                                                        | n/a                                        | n/a                                                                                                                          | Tool is replaced by direct MCP tool invocation now that MCP is first-class. Stale conversations fall back.                                                                                                                                                                                                                                                                                                                                                |
| `<user-installed MCP server>.<tool>`                          | Fallback card                                                                                 | n/a                                        | `content[]` text                                                                                                             | Default for any tool name not in the registry.                                                                                                                                                                                                                                                                                                                                                                                                            |

Two tools intentionally don't appear: `read_billing_tool` (billing context is dropped — `00_OVERVIEW.md` § 3 `core_memory`/billing row) and `ManageMemoriesTool` (memory is dropped). If they come back via a future MCP server, add rows then.

---

## 5. Approval flow rewiring

### 5.1 permission_request → DangerousOperationApprovalCard

ACP raises a JSON-RPC _request_ (not notification) when a tool wants permission. The cloud-agent SSE relay surfaces this as a discrete `permission_request` event (one of the four convenience events the SSE relay hoists alongside the raw `acp` stream — see `02_CORE.md` § 4.1). `sandboxStreamLogic.ingestPermissionRequest` consumes it, persists the request as a `PendingApproval` row (existing model, slight schema extension to carry `options[]`), and exposes it as `pendingPermissionRequest` for `maxThreadLogic` to merge into the existing `pendingApprovalsData` keyed by `proposal_id`.

For each `ToolInvocation` whose `toolCallId` matches an active `PermissionRequestRecord`, `Thread.tsx` (existing code path) renders a `DangerousOperationApprovalCard` next to the tool card. That part of the existing flow stays — the only new work is populating `pendingApprovalsData` from the new event.

The card itself reads `resolvedApprovalStatuses` (frontend) + `pendingApprovalsData` (backend) and shows either "Awaiting approval…" or the resolved status. No change.

### 5.2 Option-kind mapping

ACP permission options have `kind` ∈ `allow_once | allow_always | reject | reject_with_feedback`. Today's `DangerousOperationApprovalCard` only knows "approved / declined / auto_rejected". Mapping:

| ACP option kind        | UI affordance                                                                                                      | Resolution status sent back                                 |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------- |
| `allow_once`           | Primary "Approve" button                                                                                           | `approved` (one-shot)                                       |
| `allow_always`         | Secondary "Approve always" button — sent only if the tool's preview includes a `remember: true` flag (else hidden) | `approved` + `_posthog/permission_response.remember = true` |
| `reject`               | "Decline" button                                                                                                   | `declined`                                                  |
| `reject_with_feedback` | "Decline with feedback…" — opens text input, sends feedback string back                                            | `declined` + feedback string                                |

The send path goes through `maxThreadLogic.resolveApproval(proposalId, decision, feedback?)`, which `POST`s to the existing approval-resolution endpoint. The sandbox-runtime branch of that endpoint forwards to ACP `POST /command/` `permission_response` (cloud spec § 6.5). Same wire shape as today on the React side; new wire shape only at the SSE-relay↔agent boundary.

The card UI lives in the _input area_ today (per the comment in `DangerousOperationApprovalCard.tsx`), with the in-thread element only summarizing status. That split stays — the input-area component reads the same `options[]` and renders the four buttons accordingly. Feedback input shows when `reject_with_feedback` is chosen.

### 5.3 switch_mode / plan approval

Plan mode is now an ACP-level permission mode (`permissionMode: 'plan'`) rather than a tool call (`04_PROMPTS.md` § 4). When the agent finalizes a plan it raises a permission request with a single `allow_once` option ("Continue with plan") and an optional `reject_with_feedback` ("Refine plan"). That maps cleanly onto the existing `DangerousOperationApprovalCard` — no separate `PlanApprovalCard` needed.

**Recommendation: reuse `DangerousOperationApprovalCard` with different copy.** Add an optional `variant: 'dangerous_operation' | 'plan_approval'` prop that just swaps the title (`Approve this action?` → `Approve this plan?`), the icon (`IconWarning` → `IconNotebook`), and the body (preview is a markdown plan render instead of a JSON diff). Everything else — the options handling, the resolution path, the resolved-state styling — is identical. Keeps the surface area small.

### 5.4 Cancel from frontend

Today the user can interrupt a streaming reply via a Stop button in the input area. The sandbox-runtime branch routes that to `POST /command/` with method `cancel` (cloud spec § 6.3). `Thread.tsx` does not need to know about cancel — it's an input-area concern. Once a turn is cancelled the agent emits a `_posthog/turn_complete` with `stopReason: 'cancelled'`, which the thread renders the same way as an end-of-turn (§ 7.2).

---

## 6. Progress / thinking messages

### 6.1 \_posthog/progress → thinkingMessages

`_posthog/progress` notifications carry `{ category, message, eventGroupId, payload? }`. The SSE relay passes them through as `event: acp` frames; `sandboxStreamLogic` captures the latest one as `currentProgress` state and exposes a selector via `maxThreadLogic`.

`Thread.tsx` already renders thinking copy when `threadLoading && isLastInGroup` and an assistant turn has no text yet — `getRandomThinkingMessage()` returns a verb like "Pondering…". Replace that with: if `currentProgress?.message` is set, render that string; otherwise fall back to `getRandomThinkingMessage()`. Tiny diff — one ternary inside `MessageGroupSkeleton` / the placeholder.

When the progress event's `eventGroupId` matches the in-flight `McpToolCallMessage.id`, the _renderer_ gets to display the progress (e.g. `SessionSummarizationProgress` already does this from its accumulated updates). Otherwise the message floats at thread bottom as the global "what's it doing right now" line.

### 6.2 Status indicators on in-flight tool cards

The header on each `McpToolCallRenderer` shows status via the convention in § 2.4. Shimmering header + spinner during `in_progress`; check icon on `completed`; red X on `failed`. The existing `AssistantActionComponent` is the natural template — extract its header bits (`<IconChevronRight/>` toggle, shimmering content) into a `ToolCardHeader` component the adapters reuse.

The fallback renderer uses the same header — that's where the per-tool `displayName` is shown, with the qualified MCP name as a tooltip on hover.

---

## 7. Boundary events

### 7.1 \_posthog/run_started

Emitted once per Run by the agent-server. The SSE relay passes it through. The only UI behavior is to invalidate any in-flight "Starting…" thinking message; nothing renders directly. Useful for telemetry (Phase 5 metric: time-to-first-token).

### 7.2 \_posthog/turn_complete

End-of-turn marker. Carries `stopReason: 'end_turn' | 'tool_use' | 'cancelled' | 'error' | 'max_tokens'`. `maxThreadLogic` clears `threadLoading` on this event (today it clears on the conversation-stream's terminal message — same effect, different wire trigger).

`Thread.tsx` already conditions on `threadLoading` to show / hide actions, retry buttons, etc. No additional render logic — the stop reason is passed to the `SuccessActions` / `RetriableFailureActions` blocks via existing message status:

| stopReason   | Existing behavior                                                                                    |
| ------------ | ---------------------------------------------------------------------------------------------------- |
| `end_turn`   | Show `SuccessActions` (rate / retry).                                                                |
| `tool_use`   | Should not surface — turn isn't actually complete; the agent is mid-tool. Treat as no-op.            |
| `cancelled`  | Show "Try again" + greyed-out user message.                                                          |
| `error`      | Last assistant message gets `status: 'error'`; existing red banner.                                  |
| `max_tokens` | Show a one-time toast "Reply truncated — ask for more to continue", reuse the existing error banner. |

### 7.3 Stop-reason handling

Stop reason lives on the assistant message envelope (adapter copies it onto the trailing `AssistantMessage`'s `meta.stop_reason`). `Thread.tsx` reads it from there if it needs to differentiate the failure pill copy. None of the renderers in `messages/*` need to know about it.

---

## 8. Deletions — **deferred to post-default-on cleanup**

> **Coexistence mode** (per [`BACKWARD_COMPAT.md`](./BACKWARD_COMPAT.md) #6–#8, #14). Nothing in this section is in scope for the migration. `useMaxTool`, `MaxTool`, `toolMap`, `TOOL_DEFINITIONS`, the 17 call-site files, and the existing `UIPayloadAnswer.tsx` dispatcher all **stay untouched** during the soak. They're the LangGraph runtime's tool layer and they continue to work for LangGraph conversations.
>
> The sandbox runtime gets its tool rendering via the new registry path described in §§ 2–7, layered _alongside_ the existing dispatcher in `Thread.tsx` via an `if (agent_runtime === 'sandbox')` branch.

The cleanup work below runs **only after** the `posthog-ai-sandbox` flag is default-on for everyone _and_ a soak period confirms parity. It is tracked separately, not in this migration's phasing.

### 8.1 useMaxTool / MaxTool (cleanup phase only)

Both files deleted outright:

- `frontend/src/scenes/max/MaxTool.tsx`
- `frontend/src/scenes/max/useMaxTool.ts`

### 8.2 toolMap / TOOL_DEFINITIONS / ToolDefinition / ToolRegistration (cleanup phase only)

- `frontend/src/scenes/max/max-constants.tsx` — `TOOL_DEFINITIONS`, `ToolDefinition`, `ToolRegistration`, `RecordingsWidgetDef`, `SessionSummarizationWidgetDef`, `DEFAULT_TOOL_KEYS`, `getToolDefinition()`, `getToolDefinitionFromToolCall()`. **Kept:** `MODE_DEFINITIONS`, `SPECIAL_MODES`, `AI_GENERALLY_CAN`, `AI_GENERALLY_CANNOT`, `getToolsForMode()` — these are UI metadata for the picker / intro screen and aren't tied to runtime tool dispatch.
- `frontend/src/scenes/max/maxGlobalLogic.tsx` — `registerTool`, `deregisterTool` actions; `registeredToolMap`, `toolMap`, `tools`, `availableStaticTools`, `editInsightToolRegistered`, `toolSuggestions` selectors; `STATIC_TOOLS` constant.
- `frontend/src/scenes/max/Thread.tsx` — drop the LangGraph-only dispatch branch and the legacy `ToolCallsAnswer`, `PlanningAnswer`, `AssistantActionComponent`, `EnhancedToolCall`, `getToolCallDescriptionAndWidget`.

### 8.3 Call-site migration (cleanup phase only)

`useMaxTool` is imported by 17 files (from `grep -rn "useMaxTool\b" frontend/src/`):

```
frontend/src/scenes/insights/InsightPageHeader.spec.tsx
frontend/src/scenes/insights/InsightPageHeader.tsx
frontend/src/scenes/settings/environment/ManagedReverseProxy.tsx
frontend/src/scenes/experiments/Experiments.tsx
frontend/src/scenes/experiments/components/SummarizeExperimentButton.tsx
frontend/src/scenes/experiments/hooks/useSessionReplaySummaryMaxTool.ts
frontend/src/scenes/max/MaxTool.tsx
frontend/src/scenes/max/useMaxTool.ts
frontend/src/scenes/web-analytics/WebAnalyticsScene.tsx
frontend/src/scenes/surveys/Survey.tsx
frontend/src/scenes/surveys/wizard/SurveyWizard.tsx
frontend/src/scenes/surveys/wizard/steps/TemplateStep.tsx
frontend/src/scenes/surveys/components/SurveyOpportunityButton.tsx
frontend/src/scenes/surveys/components/AnalyzeResponsesButton.tsx
frontend/src/scenes/surveys/components/empty-state/SurveysEmptyState.tsx
frontend/src/layout/scenes/components/SceneTitleSection.tsx
frontend/src/layout/navigation-3000/Navigation.tsx
```

When (and only when) the cleanup phase runs, the per-call-site disposition is:

1. **Pure "Open Max with this prompt"** (`SummarizeExperimentButton`, `SurveyOpportunityButton`, `AnalyzeResponsesButton`, `SurveysEmptyState`, navigation entry points): drop `useMaxTool`. Replace with a direct `openSidePanel(SidePanelTab.Max, initialMaxPrompt)` + (if needed) `setActiveGroup(...)`. The "is this tool registered?" gate becomes a static check against an exported MCP tool registry.
2. **Scene "intro override"** (`InsightPageHeader`, `WebAnalyticsScene`, `Survey`, `SurveyWizard`, `TemplateStep`, `Experiments`, `ManagedReverseProxy`, `SceneTitleSection`): drop `useMaxTool`. Intro override moves to a static lookup keyed by `sceneId` in `Intro.tsx`. The `context` payload moves to the scene's `maxContext` selector (`01_CONTEXT.md` § 3).
3. **`callback` consumer — `useSessionReplaySummaryMaxTool.ts`** (experiments): the one site where a scene actually reacts to tool output. Migrate to a **read-only `useValues(maxThreadLogic)` subscription** that filters for `McpToolCallMessage`s with `toolName === 'posthog-data.experiment_session_replays_summary'` and `status === 'completed'`. Same UX, no agent-to-scene callback.
4. **Tests** (`InsightPageHeader.spec.tsx`): delete the `useMaxTool` mock and the assertions on registered tools.

That covers all 17 import sites — but again, this is **cleanup-phase work, not migration work**.

---

## 9. File-by-file move plan

Only additive changes during the migration. Every column-2 entry is one of:

- **Unchanged** — touched only by LangGraph path; not modified during the migration.
- **Modified (additive)** — branch is added; existing code path preserved verbatim.
- **New** — brand-new file.
- **Cleanup-phase only** — deferred until after default-on per § 8.

### Migration scope

| Path                                                                             | Disposition                                                                                                                                                                                                                                                                                                                 |
| -------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `frontend/src/scenes/max/Thread.tsx`                                             | **Modified (additive).** Add an `if (agent_runtime === 'sandbox')` dispatch branch above the existing LangGraph branch. Existing `isAssistantToolCallMessage` + `ToolCallsAnswer` + `getToolCallDescriptionAndWidget` rendering stays untouched.                                                                            |
| `frontend/src/scenes/max/DangerousOperationApprovalCard.tsx`                     | **Modified (additive).** Optional `variant: 'langgraph' \| 'sandbox-permission' \| 'sandbox-plan'` prop, defaults to `'langgraph'`. Existing call sites unchanged.                                                                                                                                                          |
| `frontend/src/scenes/max/approvalOperationUtils.ts`                              | **Modified (additive).** Add a parser for ACP `permission_request` payloads next to the existing `DangerousOperationResponse` parser. Existing parser unchanged.                                                                                                                                                            |
| `frontend/src/scenes/max/maxThreadLogic.tsx`                                     | **Modified (additive).** New SSE event handlers for `mcp_tool_call` / `mcp_tool_call_update` / `permission_request` / `_posthog/progress` / `_posthog/run_started` / `_posthog/turn_complete`, plus a `currentProgress` selector. Existing handlers (including `AssistantEventType.SANDBOX` already in the file) preserved. |
| `frontend/src/scenes/max/mcpToolRegistry.tsx`                                    | **New.** Registry + all `register()` calls + fallback renderer wiring.                                                                                                                                                                                                                                                      |
| `frontend/src/scenes/max/messages/adapters/CreateInsightAdapter.tsx`             | **New.** § 3.3 Example A.                                                                                                                                                                                                                                                                                                   |
| `frontend/src/scenes/max/messages/adapters/CreateNotebookAdapter.tsx`            | **New.** § 3.3 Example B.                                                                                                                                                                                                                                                                                                   |
| `frontend/src/scenes/max/messages/adapters/SummarizeSessionsAdapter.tsx`         | **New.** § 3.3 Example C.                                                                                                                                                                                                                                                                                                   |
| `frontend/src/scenes/max/messages/adapters/SearchSessionRecordingsAdapter.tsx`   | **New.** Wraps `RecordingsWidget`.                                                                                                                                                                                                                                                                                          |
| `frontend/src/scenes/max/messages/adapters/SearchErrorTrackingIssuesAdapter.tsx` | **New.** Wraps `ErrorTrackingFiltersWidget`.                                                                                                                                                                                                                                                                                |
| `frontend/src/scenes/max/messages/adapters/ExecuteSqlAdapter.tsx`                | **New.** Renders SQL + result.                                                                                                                                                                                                                                                                                              |
| `frontend/src/scenes/max/messages/adapters/TodoWriteAdapter.tsx`                 | **New.** Mirrors `PlanningAnswer` for the sandbox runtime; does not modify the original.                                                                                                                                                                                                                                    |
| `frontend/src/scenes/max/messages/adapters/WebSearchAdapter.tsx`                 | **New.** Renders Claude `web_search` result list.                                                                                                                                                                                                                                                                           |
| `frontend/src/scenes/max/messages/adapters/extractors.ts`                        | **New.** Shape-mapping helpers per § 3.3.                                                                                                                                                                                                                                                                                   |
| `frontend/src/scenes/max/messages/adapters/FallbackMcpToolRenderer.tsx`          | **New.** Generic "tool was called" card for tools without a dedicated adapter.                                                                                                                                                                                                                                              |
| `frontend/src/scenes/max/utils.ts`                                               | **Modified (additive).** Add `isMcpToolCallMessage`, `isPermissionRequestMessage` type guards.                                                                                                                                                                                                                              |
| `frontend/src/scenes/max/maxTypes.ts`                                            | **Modified (additive).** Add `McpToolCallMessage`, `PermissionRequestMessage`, `PermissionOption`, `AttachedContext` interfaces. No existing type modified or deleted.                                                                                                                                                      |

### Unchanged (migration scope)

These files are not touched at all:

- `frontend/src/scenes/max/MaxTool.tsx`
- `frontend/src/scenes/max/useMaxTool.ts`
- `frontend/src/scenes/max/max-constants.tsx`
- `frontend/src/scenes/max/maxGlobalLogic.tsx`
- `frontend/src/scenes/max/MarkdownMessage.tsx`
- `frontend/src/scenes/max/messages/UIPayloadAnswer.tsx` (continues to dispatch on `ui_payload.kind` for LangGraph)
- `frontend/src/scenes/max/messages/VisualizationArtifactAnswer.tsx`
- `frontend/src/scenes/max/messages/NotebookArtifactAnswer.tsx`
- `frontend/src/scenes/max/messages/ErrorTrackingFiltersSummary.tsx`
- `frontend/src/scenes/max/messages/ErrorTrackingIssueCard.tsx`
- `frontend/src/scenes/max/messages/RecordingsFiltersSummary.tsx`
- `frontend/src/scenes/max/messages/SessionSummarizationProgress.tsx`
- `frontend/src/scenes/max/messages/MultiQuestionForm.tsx`
- `frontend/src/scenes/max/messages/MessageTemplate.tsx`
- `frontend/src/scenes/max/messages/maxErrorTrackingWidgetLogic.ts`
- `frontend/src/scenes/max/utils/thinkingMessages.ts`
- All 17 `useMaxTool` call-site files (`InsightPageHeader.tsx`, `WebAnalyticsScene.tsx`, etc.)

### Cleanup-phase only (deferred until after default-on)

Everything listed in § 8 plus the cleanups in the table — all gated behind a separate cleanup phase that runs after the soak confirms parity. No deletions land during the migration window.

Phasing: ship the registry + adapters + new dispatch branch behind the existing `posthog-ai-sandbox` flag; flip the flag per-tool via `posthog-ai-sandbox-tool-{slug}`; the soak runs with both paths live. Once the flag defaults on for everyone, kick off the cleanup phase tracked in [`BACKWARD_COMPAT.md`](./BACKWARD_COMPAT.md) § "Cleanup roadmap".

---

## 10. Open questions

All originally-tracked questions have been resolved during planning. The bullets below capture the disposition for the record; deferred items have a `TODO.md` entry.

**Resolved cross-spec:**

- **#1 — Adapter envelope vs raw frames.** SSE relay forwards raw ACP frames (`02_CORE.md` § 4.1); `sandboxStreamLogic` (`02_CORE.md` § 6.2) merges `tool_call` + N `tool_call_update` into one `ToolInvocation` record on the frontend.
- **#10 — `mcp_tool_call` envelope.** Dedicated `event: acp` SSE event (`02_CORE.md` § 4.1); `message` stays LangGraph-only.

**Resolved decisions:**

- **#2 — Read/list/search granularity.** Keep MCP tools as they exist today in the PostHog MCP server — each sub-kind is its own first-class tool. No flattening, no in-adapter `kind` dispatch. Table rows updated in § 4.
- **#3 — Edit-existing-insight path.** Separate `edit_insight` (or equivalent) tool alongside `create_insight`, following the existing PostHog MCP server's naming convention (`query-*` for ephemeral reads + `insight-*` for writes — exact slugs owned by the MCP server). One adapter handles both create + edit; `artifact_id` discriminates.
- **#6 — `switch_mode` rendering.** Dropped. Tool no longer exists per `04_PROMPTS.md` § 4. Row marked dropped in § 4.
- **#8 — Per-tool feature-flag flow.** Trust backend exclusion. Registry has every adapter unconditionally; if the backend doesn't expose the tool, the agent can't call it and the adapter never runs.
- **#9 — `SandboxActivityPanel` retirement.** Action item — delete during cleanup once the registry handles real tool cards. Confirm no consumers outside `Thread.tsx` and `products/tasks/frontend/lib/parse-logs.ts`.

**Deferred — tracked in [`TODO.md`](./TODO.md):**

- **#4 — MultiQuestionForm answer channel.** Map onto whatever the Claude Code SDK provides for built-in form / structured-question tools. If nothing fits, deprecate `create_form` for v1 and ask clarifying questions in plain text. See `TODO.md` "MultiQuestionForm answer channel".
- **#5 — Notebook block streaming.** v1 renders the whole notebook on tool completion. Streaming is deferred. See `TODO.md` "Notebook block streaming".
- **#7 — `fix_hogql_query` UX.** Tool dropped. The fix-this-query affordance becomes a UI trigger that opens a Max conversation with a pre-filled prompt. See `TODO.md` "Insight editor → Max 'fix this query' trigger".
