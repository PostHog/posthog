# 03 — Rich UI (MCP tool-name dispatch)

This spec covers the frontend slice of the migration. The premise (locked by `00_OVERVIEW.md`): the chat scene under `frontend/src/scenes/max/` stays. No new scene, no new dispatcher framework, no callback channel from agent to scene. The only structural change is a tool-name → renderer registry plus a handful of adapter wrappers around the renderers we already have.

You are also reading this because the wire format is now ACP frames carried inside `StoredLogEntry` envelopes (see `02_CORE.md` § 4 — sketched in `00_OVERVIEW.md` § 5 / § 7 until the full doc lands). What flows in is:

- `session/update` notifications with `params.update.sessionUpdate === 'tool_call' | 'tool_call_update'`. The frontend dispatches off these, mirroring `Twig/apps/code/.../cloudToolChanges.ts`.
- `permission_request` events the cloud-agent SSE hoists out of upstream agent-server JSON-RPC requests.
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

The cloud-agent SSE (`02_CORE.md` § 4) passes ACP frames through raw, wrapped in a `StoredLogEntry` envelope. The merging from `tool_call` + N × `tool_call_update` into one coherent record happens **client-side** in `sandboxStreamLogic.ts` (`02_CORE.md` § 6). That module exposes `ToolInvocation` records — the input to this spec's registry — keyed by `toolCallId`:

```ts
interface ToolInvocation {
  toolCallId: string
  rawServerName: string         // ACP-reported MCP server, e.g. 'posthog' or '<user-installed>'
  rawToolName: string           // ACP-reported tool, e.g. 'exec', 'TodoWrite', '<user-tool>'
  innerToolName?: string        // parsed from `rawInput.command` when rawToolName === 'exec' (see § 2.2)
  resolvedKey: string           // what the registry looks up — see § 2.2 for the resolution table
  input: Record<string, unknown> // rawInput at tool_call (for `exec`, includes the wrapper `{ command }`)
  innerInput?: Record<string, unknown> // JSON-parsed inner args when innerToolName is set
  output?: unknown               // rawOutput on the final tool_call_update
  progress?: unknown             // partial result from intermediate updates
  status: 'pending' | 'in_progress' | 'completed' | 'failed'
  title?: string                 // ACP toolCall.title
  kind?: string                  // ACP toolCall.kind
  locations?: { path: string; line?: number }[]
  contentBlocks: unknown[]       // accumulated ACP `content[]` from updates
}

interface PermissionRequestRecord {
  requestId: string
  toolCallId: string
  options: PermissionOption[]    // {optionId, name, kind} where kind ∈ allow_once|allow_always|reject|reject_with_feedback
  title?: string
  description?: string
  rawToolCall: ToolInvocation
}
```

The registry described below dispatches on `ToolInvocation.resolvedKey`. The merging pattern mirrors `Twig/apps/code/src/renderer/features/task-detail/utils/cloudToolChanges.ts` — `sandboxStreamLogic` ports its walk: read `params.update.sessionUpdate`, key by `params.update.toolCallId`, merge subsequent `tool_call_update`s into the same record. **All merging is frontend-side**; the backend relay never reads tool semantics.

> **Why frontend merge:** the relay stays a thin passthrough that knows nothing about tools. Adding a new MCP tool requires zero backend change beyond exposing it as an MCP server — the frontend registry and the (optional) adapter cover the rest. See `00_OVERVIEW.md` § 2 and `02_CORE.md` § 6 for the rationale.

### 2.2 The qualified-name discriminator — single-exec mode

PostHog's MCP server runs in **single-exec mode**: only one tool, `mcp__posthog__exec`, is registered with the model (`services/mcp/src/tools/exec.ts`). The model picks the actual operation by passing a CLI-style `command` string. Five verbs:

```
tools                                  — list every tool the dispatcher exposes
search <regex>                         — search by name/title/description
info [--json] <tool>                   — show description + input schema
schema <tool> [field_path]             — drill into a specific field
call [--json] <tool> <json_input>      — invoke a tool
```

So on the wire we never see `mcp__posthog__create_insight` — we see `mcp__posthog__exec` with `rawInput = { command: "call insight-create {\"name\":...}" }`. The renderer registry has to parse the inner tool out **before** dispatch, otherwise every PostHog tool call routes to one row.

The exact parsing logic Twig uses is in `Twig/apps/code/src/renderer/features/posthog-mcp/utils/posthog-exec-display.ts:21-100` — port it verbatim into `sandboxStreamLogic`:

```ts
const POSTHOG_EXEC_TOOL_RE = /^mcp__(?:plugin_)?posthog(?:_[^_]+)*__exec$/

function resolveToolKey(serverName: string, toolName: string, input: Record<string, unknown>): {
    resolvedKey: string
    innerToolName?: string
    innerInput?: Record<string, unknown>
} {
    const fullName = `mcp__${serverName}__${toolName}`

    // Single-exec mode: parse the verb + inner tool out of `command`
    if (POSTHOG_EXEC_TOOL_RE.test(fullName) && typeof input.command === 'string') {
        const verbMatch = input.command.match(/^\s*(tools|search|info|schema|call)(?:\s+([\s\S]*))?\s*$/)
        if (!verbMatch) return { resolvedKey: '__posthog_exec_unknown__' }

        const verb = verbMatch[1] as 'tools' | 'search' | 'info' | 'schema' | 'call'
        const rest = (verbMatch[2] ?? '').trim()

        if (verb !== 'call') {
            // Discovery verbs render as a single GenericExecAdapter card (one row)
            return { resolvedKey: `__posthog_exec_${verb}__` }
        }

        // verb === 'call' — extract inner tool name + JSON body
        const callMatch = rest.match(/^(?:--json\s+)?([a-zA-Z0-9_-]+)\s*([\s\S]*)$/)
        if (!callMatch) return { resolvedKey: '__posthog_exec_unknown__' }

        const innerToolName = callMatch[1]
        const jsonBody = (callMatch[2] ?? '').trim()
        let innerInput: Record<string, unknown> = {}
        if (jsonBody) {
            try { innerInput = JSON.parse(jsonBody) } catch { /* leave empty */ }
        }
        return { resolvedKey: innerToolName, innerToolName, innerInput }
    }

    // Non-exec MCP tools (user-installed servers) and Claude SDK built-ins (TodoWrite, WebSearch)
    return { resolvedKey: toolName }
}
```

Dual lookup at registry time:

| Case | `resolvedKey` example | Registry lookup |
|---|---|---|
| Single-exec `call` — known inner tool | `'insight-create'` | `registry['insight-create']` |
| Single-exec `call` — unknown inner tool | `'<some-new-tool>'` | falls through to `FallbackRenderer` |
| Single-exec discovery verb | `'__posthog_exec_tools__'`, `'__posthog_exec_search__'`, etc. | `registry['__posthog_exec_*__']` → shared `ExecVerbAdapter` |
| Single-exec malformed `command` | `'__posthog_exec_unknown__'` | `FallbackRenderer` (verbatim raw display) |
| Non-exec MCP tool | `'<server>.<tool>'` (rawToolName as-is) | `registry[rawToolName]` or `registry[fullName]` |
| Claude SDK built-in (`TodoWrite`, `WebSearch`) | `'TodoWrite'` | `registry['TodoWrite']` |

This is the **only** PostHog-specific normalization the registry needs. Non-PostHog MCP servers (user-installed) are not single-exec — their tools come through as discrete `mcp__<server>__<tool>` names. They look up directly.

`PermissionRequestRecord` also runs through `resolveToolKey` because the permission card shows the same input shape the user is asked to approve — see `posthog-exec-display.ts:117-130` (`formatPosthogExecBody`) for the pretty-print.

### 2.3 Thread.tsx additive case

The dispatch is purely additive — drop a new branch into the `Message` IIFE in `Thread.tsx`, just above the `isMultiVisualizationMessage` branch. Sketch:

```tsx
} else if (isMcpToolCallMessage(message)) {
    // resolvedKey comes from sandboxStreamLogic per § 2.2 (parses single-exec command)
    const entry = lookupMcpToolRenderer(message.resolvedKey)
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
  /**
   * Registry key. For single-exec PostHog tools, this is the **inner** tool name
   * parsed from `rawInput.command` (e.g. "execute-sql", "insight-create"); for
   * `exec`'s discovery verbs, the sentinel "__posthog_exec_tools__" etc.; for
   * non-exec MCP tools and Claude built-ins, the wire `toolName` directly
   * (e.g. "TodoWrite", "WebSearch", "mcp__<user-installed>__<tool>"). See § 2.2.
   */
  key: string
  /** Display name / icon for fallback rendering and for the tool-call header line. */
  displayName: string
  icon: JSX.Element
  Renderer: ComponentType<McpToolRendererProps>
}

export interface McpToolRegistry {
  register(entry: McpToolRegistryEntry): void
  lookup(toolName: string): McpToolRegistryEntry | null
}
```

`lookup(key)` accepts the `resolvedKey` from § 2.2; returns `null` when nothing matches and `Thread.tsx` falls back to the generic renderer (§ 3.4).

### 3.2 Registration

Single module-level `mcpToolRegistry` instance. All entries registered at module load — no dynamic registration, no hooks, no scene callbacks:

```ts
// mcpToolRegistry.tsx
class MapBackedRegistry implements McpToolRegistry {
  /* ... */
}
export const mcpToolRegistry = new MapBackedRegistry()

// PostHog MCP tool — inner name parsed from `exec`'s `call <tool>` verb
mcpToolRegistry.register({
  key: 'execute-sql',
  displayName: 'Execute SQL',
  icon: iconForType('insight/hog'),
  Renderer: ExecuteSqlAdapter,
})

// Single-exec discovery verb — shared adapter
mcpToolRegistry.register({
  key: '__posthog_exec_tools__',
  displayName: 'List tools',
  icon: iconForType('list'),
  Renderer: ExecVerbAdapter,
})

// Claude SDK built-in — registered with the raw wire name
mcpToolRegistry.register({
  key: 'TodoWrite',
  displayName: 'Plan',
  icon: iconForType('todo'),
  Renderer: TodoWriteAdapter,
})

// ...one block per row from § 4, grouped by section with header comments.
```

The static tool universe consists of: (1) the 377 v2-eligible inner tool names from `services/mcp/schema/tool-definitions-all.json` — most fall to fallback, ~15 get custom adapters per § 4.2; (2) four discovery-verb sentinels per § 4.1; (3) Claude SDK built-ins (`TodoWrite`, `WebSearch`); (4) PostHog Code MCP tools (fallback); (5) user-installed MCPs (fallback). Locality matters more than abstraction here — keep all registrations in this one file so the surface is greppable.

### 3.3 Adapter pattern — worked examples

Adapters are thin wrappers (5–15 lines) that extract props from `message.rawInput` / `message.content` / `message.rawOutput` and call the existing component. They live next to the registry in a `frontend/src/scenes/max/messages/adapters/` directory, one file per MCP tool.

**Example A — Visualization artifact adapter** (covers `insight-create` / `insight-update` / `insight-query`):

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

`extractVisualizationArtifact(message)` pulls the artifact id and `VisualizationArtifactContent` out of `message.rawOutput` (the MCP tool returns it directly; backend MCP server is responsible for matching the existing shape). The `innerToolName` discriminates: `insight-create` / `insight-update` produce a saved artifact with `artifact_id`; `insight-query` is ephemeral (`source: ArtifactSource.None`). `isEditingInsight` / `activeTabId` / `activeSceneId` collapse to `false`/`null` because the contextual-edit flow is dead — only the create/update/query paths remain.

**Example B — Notebook adapter** (covers `notebooks-create`):

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

**Example C — Session summarization adapter** (covers `session-recording-summarize`):

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

When `mcpToolRegistry.lookup(resolvedKey)` returns `null` (user-installed MCP, unknown server, an inner tool we haven't wired yet, etc.), `Thread.tsx` falls back to `FallbackMcpToolRenderer` defined in `UIPayloadAnswer.tsx` (repurposed as the registry's spillover home — the kind-based dispatcher inside it is gone, replaced by this single fallback). It renders a generic tool card:

- Header line: `<icon> <message.title || message.innerToolName || message.rawToolName>` plus status badge.
- Expandable accordion: `rawInput` JSON, then `content[]` (text frames pretty-printed; non-text frames as JSON), then `rawOutput` if present.
- For `failed` status, top-level red message with `error.message`.

This is the catch-all that lets us ship the registry incrementally — every backend MCP tool that's enabled but not yet wired through an adapter still renders something sensible.

The `RecordingsWidget`, `ErrorTrackingFiltersWidget`, `SummarizeSessionsWidget` exports stay (`Thread.tsx` and adapters import them), but `UIPayloadAnswer` itself shrinks to just `FallbackMcpToolRenderer` + those widget exports.

---

## 4. Tool → renderer mapping table

Source of truth for tool names is `services/mcp/schema/tool-definitions-all.json` (filter by `new_mcp: true` — 377 v2-eligible tools at last count). Single-exec mode means the model only sees `mcp__posthog__exec`; the rows below dispatch on the **inner** tool name parsed out of `rawInput.command` per § 2.2. The "MCP tool" column lists the inner tool name as `services/mcp/definitions/*.yaml` defines it.

> The vast majority of tools render via the **fallback card** (§ 3.4). Custom adapters land per-tool, behind `posthog-ai-sandbox-tool-{slug}`, only when there's a real product reason — a widget, an artifact, a CTA. The default is "trust the fallback."

### 4.1 Single-exec wrapper rows (the `exec` verbs themselves)

These are not real tool calls — they're discovery / introspection calls the model makes against the dispatcher. One shared adapter handles all four verbs; resolves a one-line header text per `posthog-exec-display.ts:39-100`.

| `resolvedKey` (from § 2.2)    | Frontend renderer              | Header                                | Notes                                                                                |
| ----------------------------- | ------------------------------ | ------------------------------------- | ------------------------------------------------------------------------------------ |
| `__posthog_exec_tools__`      | `ExecVerbAdapter` (new)        | `List tools`                          | Returns name list. Output is the tool catalog string — collapsible by default.       |
| `__posthog_exec_search__`     | `ExecVerbAdapter` (new)        | `Search tools <regex>`                | Regex argument shown in header. Output is the match list.                            |
| `__posthog_exec_info__`       | `ExecVerbAdapter` (new)        | `Read <tool_name>`                    | Tool name folded into header (no args slot).                                         |
| `__posthog_exec_schema__`     | `ExecVerbAdapter` (new)        | `Inspect <tool>.<field_path>`         | Dotted locator.                                                                      |
| `__posthog_exec_unknown__`    | `FallbackMcpToolRenderer`      | `posthog - exec`                      | Malformed `command` — show raw input.                                                |

### 4.2 PostHog MCP tools — custom adapters

These rows are for inner tool names parsed from `exec`'s `call <tool>` verb. Tools not listed here fall through to `FallbackMcpToolRenderer`.

| Inner tool name(s)                                                          | Frontend renderer                                                                             | Input extractor (`innerInput`)             | Output extractor (`rawOutput` / `content`)                                                                                   | Notes                                                                                                                                                                                                                                                                                                                                                |
| --------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `execute-sql`                                                               | `ExecuteSqlAdapter` (new)                                                                     | `query: string`                            | `VisualizationArtifactContent` when tabular; HogQL result blob in `content[]` otherwise                                      | Mirrors today's `executedSQLQuery` snippet in `AssistantActionComponent`. Code-snippet header + result table.                                                                                                                                                                                                                                        |
| `insight-create` / `insight-update`                                         | `CreateInsightAdapter` (new) → `VisualizationArtifactAnswer`                                  | `name`, `query` / `derived_from_query`     | `rawOutput.id`, `rawOutput.short_id`, `rawOutput.url`                                                                        | One adapter handles both; `artifact_id` discriminates. See § 3.3 Example A.                                                                                                                                                                                                                                                                          |
| `insight-query`                                                             | `CreateInsightAdapter` variant — ephemeral (no artifact)                                      | `query` shape                              | Inline result blob — no insight saved                                                                                        | The "read-only / ephemeral query" path. Same adapter, `source: ArtifactSource.None`.                                                                                                                                                                                                                                                                 |
| `query-trends` / `query-funnel` / `query-retention` / `query-stickiness` / `query-paths` / `query-lifecycle` / `query-trends-actors` / `query-lifecycle-actors` / `query-llm-trace` / `query-llm-traces-list` | `QueryWrapperAdapter` (new) → `VisualizationArtifactAnswer`                                   | typed `AssistantTrendsQuery` etc.          | `VisualizationArtifactContent` with `source: ArtifactSource.None`                                                            | Typed query-wrapper tools (`services/mcp/definitions/query-wrappers.yaml`). One adapter for all 10 — schema-driven; the typed query is rendered via the existing `Query` shell.                                                                                                                                                                       |
| `dashboard-create` / `dashboard-update`                                     | `UpsertDashboardAdapter` (new)                                                                | `name`, `tiles`, …                         | `rawOutput.id`, `rawOutput.url`                                                                                              | v1: status line + "View dashboard" CTA. Full embed deferred.                                                                                                                                                                                                                                                                                         |
| `notebooks-create`                                                          | `CreateNotebookAdapter` → `NotebookArtifactAnswer`                                            | `title`, `content`                         | `rawOutput.short_id`, `rawOutput.title`, `rawOutput.url`                                                                     | See § 3.3 Example B. **v1 renders the whole notebook on tool completion — no block-by-block streaming.** Streaming deferred per [`TODO.md`](./TODO.md) "Notebook block streaming". The component already supports streaming if `blocks` arrive incrementally, so the future switch is wire-format only.                                              |
| `session-recording-summarize`                                               | `SummarizeSessionsAdapter` (new) → `SessionSummarizationProgress` + `SummarizeSessionsWidget` | `session_ids?`, `summary_title?`           | `content[]` streamed `SessionSummarizationUpdate` JSON frames; `rawOutput.{ session_group_summary_id, title }` on completion | See § 3.3 Example C.                                                                                                                                                                                                                                                                                                                                 |
| `query-session-recordings-list`                                             | `SearchSessionRecordingsAdapter` (new) → `RecordingsWidget`                                   | `filters: RecordingUniversalFilters`       | `rawOutput.filters`                                                                                                          | One-line adapter — the input is already a filter object, the widget renders the list inline.                                                                                                                                                                                                                                                          |
| `query-error-tracking-issues-list` / `query-error-tracking-issue` / `query-error-tracking-issue-events` | `ErrorTrackingAdapter` (new) → `ErrorTrackingFiltersWidget`                                   | `search_query` / `issue_id` / `filters`    | `rawOutput: MaxErrorTrackingSearchResponse` (existing schema)                                                                | Reuses `ErrorTrackingFiltersWidget`. One adapter handles all three; the issue-detail variant gets a card with stack trace summary instead of the filters widget.                                                                                                                                                                                     |
| `read-data-schema` / `read-data-warehouse-schema`                           | `FallbackMcpToolRenderer`                                                                     | `query: { kind, … }`                       | `content[]` text frames; large schemas truncated                                                                             | Description-driven header (e.g. "Read events schema", "Inspected warehouse table"). Stays on fallback — these are discovery calls, no widget needed.                                                                                                                                                                                                  |
| `create-feature-flag` / `update-feature-flag` / `delete-feature-flag` / `feature-flag-get` | `FallbackMcpToolRenderer`                                                                     | `key`, `filters`                           | `rawOutput.id`, `rawOutput.url`                                                                                              | "Open flag" CTA via fallback's URL handling.                                                                                                                                                                                                                                                                                                         |
| `experiment-create` / `experiment-update` / `experiment-launch` / `experiment-end` / `experiment-pause` / `experiment-resume` / `experiment-archive` / `experiment-results-get` / `experiment-stats` / `experiment-timeseries-results` | `FallbackMcpToolRenderer`                                                                     | varies                                     | `rawOutput.id`, `rawOutput.url`                                                                                              | All experiment lifecycle tools share fallback. Worth a custom card later if experiment-creation becomes a common Max workflow.                                                                                                                                                                                                                       |
| `survey-create` / `survey-update` / `survey-stats` / `surveys-get-all`      | `FallbackMcpToolRenderer`                                                                     | varies                                     | `rawOutput.id`, `rawOutput.url`                                                                                              | "Open survey" CTA via fallback.                                                                                                                                                                                                                                                                                                                      |
| `alert-create` / `alert-update` / `alert-delete` / `alert-simulate`         | `FallbackMcpToolRenderer`                                                                     | `action`, `alert`                          | `rawOutput.id`                                                                                                               | "View alert" CTA via fallback.                                                                                                                                                                                                                                                                                                                       |
| `user-interview-topics-create` / `user-interview-topics-list` (and the rest of the `user-interview-topics-*` family) | `FallbackMcpToolRenderer`                                                                     | varies                                     | `rawOutput.id`, `rawOutput.url`                                                                                              | Fallback. Could later get a themes widget for analysis tools.                                                                                                                                                                                                                                                                                        |
| `docs-search`                                                               | `FallbackMcpToolRenderer`                                                                     | `query`                                    | Result list with URLs                                                                                                        | Text + links.                                                                                                                                                                                                                                                                                                                                        |
| `agent-feedback`                                                            | (hidden — non-renderable)                                                                     | n/a                                        | n/a                                                                                                                          | Internal feedback channel; not part of the user-visible thread.                                                                                                                                                                                                                                                                                      |
| `debug-mcp-ui-apps`                                                         | (hidden in production; rendered for `posthog-ai-sandbox-debug` flag users only)               | n/a                                        | n/a                                                                                                                          | Internal UI-app test surface.                                                                                                                                                                                                                                                                                                                        |

### 4.3 Non-exec MCP servers + Claude built-ins

These tools come through as discrete `mcp__<server>__<tool>` (or built-in) names — no single-exec parsing, no `command` field. Direct registry lookup.

| `rawToolName`                       | Frontend renderer                                                       | Notes                                                                                                                                                                                                                                                                                            |
| ----------------------------------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `TodoWrite` (Claude SDK built-in)   | `TodoWriteAdapter` (new) → `PlanningAnswer` (extract from `Thread.tsx`) | `PlanningAnswer` already exists in `Thread.tsx`. Lift it to its own file (`messages/PlanningAnswer.tsx`) so the adapter can import it cleanly. `04_PROMPTS.md` § 5.1 confirms we use the SDK built-in — no `posthog-tasks` MCP server.                                                            |
| `WebSearch` (Claude SDK built-in)   | `WebSearchAdapter` (new)                                                | Same display as today's `server_tool_use` block — header `Searched the web for **<query>**` plus a list of titles linking out. Gated per-team by LLM gateway routing (see [`TODO.md`](./TODO.md) "Web search tool placement").                                                                    |
| `mcp__<user-installed>__*`          | `FallbackMcpToolRenderer`                                               | Default for any user-installed MCP server. The fallback's `rawInput`/`rawOutput` accordion handles arbitrary shapes. (Note: there is no separate `posthog-code` MCP server — PostHog Code is a *consumer* of the same single-exec `posthog` server. Legacy `TaskTool` family — if migrated — becomes inner tools of `posthog`, tracked in [`TODO.md`](./TODO.md).) |
| ~~`switch_mode`~~                   | **Dropped** — tool no longer exists per `04_PROMPTS.md` § 4.            | Stale conversations that reference it fall back to the generic card.                                                                                                                                                                                                                             |
| ~~`manage_memories`~~               | **Dropped** — memory is dropped per `00_OVERVIEW.md` § 3.               | Stale conversations fall back.                                                                                                                                                                                                                                                                   |
| ~~`call_mcp_server`~~               | **Dropped** — replaced by direct MCP tool invocation.                   | Stale conversations fall back.                                                                                                                                                                                                                                                                   |
| ~~`create_form`~~                   | **Deferred** — see [`TODO.md`](./TODO.md) "MultiQuestionForm answer channel".                                                                                                                                                                                                                                                            |
| ~~`fix_hogql_query`~~               | **Dropped** — replaced by UI trigger; see [`TODO.md`](./TODO.md) "Insight editor → Max 'fix this query' trigger".                                                                                                                                                                                                                                  |

### 4.4 Bias for fallback

The 377-tool catalog is too large to wire each into a custom adapter. The rule of thumb:

1. **Tool returns or modifies an entity with a URL** → fallback is fine (it renders the URL as a CTA).
2. **Tool returns tabular results that exist as a PostHog UI widget** (insights, dashboards, recordings, error issues, notebooks) → custom adapter that delegates to the widget.
3. **Tool streams progress** (summarize, long-running query) → custom adapter that consumes the streaming `content[]`.
4. **Everything else** → fallback. Promote to custom adapter only when product/eval data shows the fallback is degrading user experience.

The fallback card (§ 3.4) renders `rawInput` JSON, `content[]` text, and `rawOutput` with a "Open <link>" CTA when `rawOutput.url` is present. That's sufficient for the long tail.

---

## 5. Approval flow rewiring

### 5.1 permission_request → DangerousOperationApprovalCard

ACP raises a JSON-RPC _request_ (not notification) when a tool wants permission. The cloud-agent cloud-agent SSE surfaces this as a discrete `permission_request` event (one of the four convenience events the cloud-agent SSE hoists alongside the raw `acp` stream — see `02_CORE.md` § 4.1). `sandboxStreamLogic.ingestPermissionRequest` consumes it, persists the request as a `PendingApproval` row (existing model, slight schema extension to carry `options[]`), and exposes it as `pendingPermissionRequest` for `maxThreadLogic` to merge into the existing `pendingApprovalsData` keyed by `proposal_id`.

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

`_posthog/progress` notifications carry `{ category, message, eventGroupId, payload? }`. The cloud-agent SSE passes them through as `event: acp` frames; `sandboxStreamLogic` captures the latest one as `currentProgress` state and exposes a selector via `maxThreadLogic`.

`Thread.tsx` already renders thinking copy when `threadLoading && isLastInGroup` and an assistant turn has no text yet — `getRandomThinkingMessage()` returns a verb like "Pondering…". Replace that with: if `currentProgress?.message` is set, render that string; otherwise fall back to `getRandomThinkingMessage()`. Tiny diff — one ternary inside `MessageGroupSkeleton` / the placeholder.

When the progress event's `eventGroupId` matches the in-flight `McpToolCallMessage.id`, the _renderer_ gets to display the progress (e.g. `SessionSummarizationProgress` already does this from its accumulated updates). Otherwise the message floats at thread bottom as the global "what's it doing right now" line.

### 6.2 Status indicators on in-flight tool cards

The header on each `McpToolCallRenderer` shows status via the convention in § 2.4. Shimmering header + spinner during `in_progress`; check icon on `completed`; red X on `failed`. The existing `AssistantActionComponent` is the natural template — extract its header bits (`<IconChevronRight/>` toggle, shimmering content) into a `ToolCardHeader` component the adapters reuse.

The fallback renderer uses the same header — that's where the per-tool `displayName` is shown, with the qualified MCP name as a tooltip on hover.

---

## 7. Boundary events

### 7.1 \_posthog/run_started

Emitted once per Run by the agent-server. The cloud-agent SSE passes it through. The only UI behavior is to invalidate any in-flight "Starting…" thinking message; nothing renders directly. Useful for telemetry (Phase 5 metric: time-to-first-token).

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
3. **`callback` consumer — `useSessionReplaySummaryMaxTool.ts`** (experiments): the one site where a scene actually reacts to tool output. Migrate to a **read-only `useValues(maxThreadLogic)` subscription** that filters for `McpToolCallMessage`s where `innerToolName === 'session-recording-summarize'` (or whatever the experiment-scoped variant slug becomes — confirm with AI team) and `status === 'completed'`. Same UX, no agent-to-scene callback.
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

- **#1 — Adapter envelope vs raw frames.** cloud-agent SSE forwards raw ACP frames (`02_CORE.md` § 4.1); `sandboxStreamLogic` (`02_CORE.md` § 6.2) merges `tool_call` + N `tool_call_update` into one `ToolInvocation` record on the frontend.
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
