/**
 * Thread shapes for the sandbox agent runtime (`agent_runtime === 'sandbox'`).
 *
 * The sandbox path consumes the products/tasks SSE endpoint directly (the same endpoint
 * PostHog Code uses). `sandboxStreamLogic` parses the raw wire frames (typed in
 * `./sandboxWireTypes`) into the `ToolInvocation` / `ThreadItem` state the renderer consumes.
 */

import type { PermissionOption } from './sandboxWireTypes'

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
    /**
     * Registry lookup key — the inner tool name for single-exec `call` commands, a
     * `__posthog_exec_*__` sentinel for discovery verbs, or the wire tool name otherwise.
     */
    resolvedKey: string
    /** Stable SDK tool name from `_meta.claudeCode.toolName` — set for Claude built-ins, which carry no wire `toolName`. */
    claudeToolName?: string
    /** rawInput at `tool_call` time (for `exec`, includes the wrapper `{ command }`). */
    input: Record<string, unknown>
    /** JSON-parsed inner args when `innerToolName` is set. */
    innerInput?: Record<string, unknown>
    /** rawOutput on the final `tool_call_update`. */
    output?: unknown
    /** Error carried by a failed `tool_call_update` (from the update or its notification envelope). */
    error?: { message?: string } | null
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

export type ThreadItemType =
    | 'human_message'
    | 'assistant_message'
    | 'assistant_thought'
    | 'tool_invocation'
    | 'turn_separator'
    | 'error'

/**
 * An ordered, append-only entry the renderer consumes. Human messages, text chunks, streamed
 * reasoning ("thoughts"), tool-invocation references, run-lifecycle markers, and inline errors all
 * flow through this list.
 */
export interface ThreadItem {
    /** Stable id — message buffer id, tool call id, or a generated separator/error id. */
    id: string
    type: ThreadItemType
    /** For `human_message`, `assistant_message`, and `assistant_thought` items. */
    text?: string
    /** Whether the assistant message buffer is finalized. */
    complete?: boolean
    /** For `tool_invocation` items — the keyed tool call id (look up in `toolInvocations`). */
    toolCallId?: string
    /** For `error` items. */
    errorMessage?: string
    /**
     * For `error` items — distinguishes a friendlier agent-crash affordance (`crash`) from a
     * raw error line (`error`, the default). Drives the copy/styling branch in the renderer.
     */
    variant?: 'error' | 'crash'
}

/**
 * A pending ACP `permission_request` surfaced by the products/tasks stream, rendered by
 * `SandboxPermissionInput` in the input area.
 */
export interface PermissionRequestRecord {
    requestId: string
    toolCallId: string
    /** Canonical ACP tool name (`mcp__posthog__exec`, or a built-in like `Bash`) — drives the default permission policy. */
    toolName: string
    options: PermissionOption[]
    title?: string
    description?: string
    rawToolCall: ToolInvocation
}
