/**
 * Wire + thread types for the sandbox (cloud-agent) runtime.
 *
 * These describe the ACP (Agent Client Protocol) frames the cloud-agent run stream
 * emits and the thread-shaped state `sandboxStreamLogic` folds them into. They are
 * intentionally separate from the LangGraph `RootAssistantMessage` family — the two
 * runtimes coexist for the whole rollout (see docs/internal/posthog-ai-migration).
 *
 * Scope for I1.3: skeleton shapes consumed by the stream processor and the MCP tool
 * registry. Reconnect/backoff hardening and the full renderer surface land later.
 */

/** ACP `tool_call.status` — pending before any progress, terminal at the end. */
export type ToolInvocationStatus = 'pending' | 'in_progress' | 'completed' | 'failed'

/** A file/range an agent tool reported touching (ACP `toolCall.locations`). */
export interface ToolInvocationLocation {
    path: string
    line?: number
}

/**
 * One agent tool invocation, merged from a `tool_call` creation frame and N subsequent
 * `tool_call_update` frames keyed on `toolCallId`. This is the input the MCP tool
 * registry dispatches on (via `resolvedKey`).
 */
export interface ToolInvocation {
    toolCallId: string
    /** ACP-reported MCP server, e.g. 'posthog' or a user-installed server. */
    rawServerName: string
    /** ACP-reported tool, e.g. 'exec', 'TodoWrite', or a user tool. */
    rawToolName: string
    /** Parsed from `input.command` when `rawToolName === 'exec'` — see resolveToolKey. */
    innerToolName?: string
    /** What the registry looks up. See mcpToolRegistry/resolveToolKey for the resolution table. */
    resolvedKey: string
    /** rawInput at `tool_call`. For `exec`, includes the wrapper `{ command }`. */
    input: Record<string, unknown>
    /** JSON-parsed inner args when `innerToolName` is set. */
    innerInput?: Record<string, unknown>
    /** rawOutput on the final `tool_call_update`. */
    output?: unknown
    /** Partial result from intermediate updates. */
    progress?: unknown
    status: ToolInvocationStatus
    title?: string
    /** ACP `toolCall.kind`. */
    kind?: string
    locations?: ToolInvocationLocation[]
    /** Accumulated ACP `content[]` from updates. */
    contentBlocks: unknown[]
}

/** A permission option offered alongside a permission request (ACP). */
export interface PermissionOption {
    optionId: string
    name: string
    kind: 'allow_once' | 'allow_always' | 'reject' | 'reject_with_feedback'
}

/** A pending permission request the user must resolve before a tool proceeds. */
export interface PermissionRequestRecord {
    requestId: string
    toolCallId: string
    options: PermissionOption[]
    title?: string
    description?: string
    rawToolCall: ToolInvocation
}

/** Ordered, append-only items the renderer consumes from the stream. */
export type ThreadItem =
    | { kind: 'assistant_message'; id: string; text: string; complete: boolean }
    | { kind: 'tool_invocation'; toolCallId: string }
    | { kind: 'permission_request'; requestId: string }
    | { kind: 'error'; id: string; message: string }
    | { kind: 'turn_complete'; id: string }

/** SSE connection lifecycle states owned by sandboxStreamLogic. */
export type SseStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed' | 'error'

/** Terminal/lifecycle status of the underlying cloud-agent Run. */
export type RunStatus = 'queued' | 'in_progress' | 'completed' | 'failed' | 'cancelled'

/**
 * The raw ACP envelope persisted per stream event and replayed from `GET /log/`.
 * `sandboxStreamLogic.ingestAcpFrame` walks `notification.method` to fold each frame
 * into `ToolInvocation`/thread state. Mirrors the `ACPNotification` shape consumed by
 * `products/tasks/frontend/lib/parse-logs.ts` — kept structurally compatible on purpose.
 */
export interface StoredLogEntry {
    type: 'notification'
    timestamp?: string
    notification: {
        jsonrpc?: string
        method?: string
        id?: number
        params?: Record<string, unknown>
        result?: Record<string, unknown>
    }
}

/** Shape of `params.update` on an ACP `session/update` notification. */
export interface AcpSessionUpdate {
    sessionUpdate?: string
    content?: { type: string; text?: string }
    toolCallId?: string
    title?: string
    status?: string
    kind?: string
    locations?: ToolInvocationLocation[]
    rawInput?: Record<string, unknown>
    rawOutput?: unknown
    _meta?: { claudeCode?: { toolName?: string; toolResponse?: unknown }; serverName?: string }
}
