/**
 * Wire + thread shapes for the sandbox agent runtime (`agent_runtime === 'sandbox'`).
 *
 * The sandbox path consumes the products/tasks SSE endpoint directly (the same endpoint
 * PostHog Code uses). `sandboxStreamLogic` parses the raw ACP frames carried inside
 * `StoredLogEntry` envelopes into the `ToolInvocation` / `ThreadItem` state the renderer
 * consumes. See docs/internal/posthog-ai-migration/02_CORE.md §§ 4.1, 6.2 and
 * 03_RICH_UI.md §§ 2.1, 2.2.
 */

/** ACP notification body — the JSON-RPC payload carried inside a `StoredLogEntry`. */
export interface AcpNotification {
    method?: string
    params?: Record<string, unknown>
    result?: unknown
    error?: { message?: string; code?: number } | null
}

/**
 * Wire envelope around a single ACP notification. The products/tasks stream emits these as
 * the bulk of `data.type === 'notification'` traffic. See 02_CORE.md glossary.
 */
export interface StoredLogEntry {
    type: 'notification'
    timestamp?: string
    notification: AcpNotification
}

export type ToolInvocationStatus = 'pending' | 'in_progress' | 'completed' | 'failed'

/**
 * One merged tool call: a `tool_call` creation plus N × `tool_call_update`s folded into a
 * single record keyed on `toolCallId`. The single-exec `posthog` MCP server runs one outer
 * `exec` tool; the inner tool name is what the renderer keys on (`resolvedKey`).
 */
export interface ToolInvocation {
    toolCallId: string
    /** ACP-reported MCP server, e.g. 'posthog' or '<user-installed>'. */
    rawServerName: string
    /** ACP-reported tool, e.g. 'exec', 'TodoWrite', '<user-tool>'. */
    rawToolName: string
    /** Parsed inner tool name when `rawToolName === 'exec'` — e.g. 'insight-create'. */
    innerToolName?: string
    /** Registry lookup key — see 03_RICH_UI.md § 2.2 resolution table. */
    resolvedKey: string
    /** rawInput at `tool_call` time (for `exec`, includes the wrapper `{ command }`). */
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
    locations?: { path: string; line?: number }[]
    /** Accumulated ACP `content[]` from updates. */
    contentBlocks: unknown[]
}

export type ThreadItemType = 'assistant_message' | 'tool_invocation' | 'turn_separator' | 'error'

/**
 * An ordered, append-only entry the renderer consumes. Text chunks, tool-invocation
 * references, run-lifecycle markers, and inline errors all flow through this list.
 */
export interface ThreadItem {
    /** Stable id — message buffer id, tool call id, or a generated separator/error id. */
    id: string
    type: ThreadItemType
    /** For `assistant_message` items. */
    text?: string
    /** Whether the assistant message buffer is finalized. */
    complete?: boolean
    /** For `tool_invocation` items — the keyed tool call id (look up in `toolInvocations`). */
    toolCallId?: string
    /** For `error` items. */
    errorMessage?: string
}

export interface PermissionOption {
    optionId: string
    name: string
    kind: 'allow_once' | 'allow_always' | 'reject' | 'reject_with_feedback'
}

/**
 * A pending ACP `permission_request` surfaced by the products/tasks stream. Ingested in I3
 * (`02_CORE.md` § 5.5) and bound to `DangerousOperationApprovalCard`.
 */
export interface PermissionRequestRecord {
    requestId: string
    toolCallId: string
    options: PermissionOption[]
    title?: string
    description?: string
    rawToolCall: ToolInvocation
}
