const POSTHOG_EXEC_TOOL_RE = /^mcp__(?:plugin_)?posthog(?:_[^_]+)*__exec$/

export interface ResolvedToolKey {
    resolvedKey: string
    innerToolName?: string
    innerInput?: Record<string, unknown>
}

export interface ResolvableToolCall {
    rawServerName: string
    rawToolName: string
    input: Record<string, unknown>
    meta?: unknown
}

export interface ResolvedToolCall extends ResolvedToolKey {
    claudeToolName?: string
}

/** Reads `_meta.claudeCode` off a tool frame's `_meta` without trusting its shape. */
export function getClaudeCodeMeta(meta: unknown): Record<string, unknown> | undefined {
    if (typeof meta !== 'object' || meta === null) {
        return undefined
    }
    const claudeCode = (meta as { claudeCode?: unknown }).claudeCode
    return typeof claudeCode === 'object' && claudeCode !== null ? (claudeCode as Record<string, unknown>) : undefined
}

/** Stable SDK tool name (`"Edit"`, `"TodoWrite"`) from `_meta.claudeCode.toolName`; undefined when absent. */
export function extractClaudeToolName(meta: unknown): string | undefined {
    const claudeCode = getClaudeCodeMeta(meta)
    return typeof claudeCode?.toolName === 'string' && claudeCode.toolName ? claudeCode.toolName : undefined
}

/**
 * Resolves the registry key for a tool call. The single-exec `posthog` MCP server exposes one
 * outer `exec` tool; the inner tool name is parsed out of `rawInput.command`. Non-exec MCP tools
 * and Claude built-ins look up by their wire name directly. Claude built-ins carry no wire
 * `toolName`, so `claudeToolName` (from `_meta.claudeCode.toolName`) is preferred as the fallback.
 */
export function resolveToolKey(
    serverName: string,
    toolName: string,
    input: Record<string, unknown>,
    claudeToolName?: string
): ResolvedToolKey {
    const fullName = `mcp__${serverName}__${toolName}`
    const isPostHogExecTool =
        POSTHOG_EXEC_TOOL_RE.test(fullName) ||
        POSTHOG_EXEC_TOOL_RE.test(toolName) ||
        (claudeToolName ? POSTHOG_EXEC_TOOL_RE.test(claudeToolName) : false)

    if (isPostHogExecTool && typeof input.command === 'string') {
        const verbMatch = input.command.match(/^\s*(tools|search|info|schema|call)(?:\s+([\s\S]*))?\s*$/)
        if (!verbMatch) {
            return { resolvedKey: '__posthog_exec_unknown__' }
        }

        const verb = verbMatch[1] as 'tools' | 'search' | 'info' | 'schema' | 'call'
        const rest = (verbMatch[2] ?? '').trim()

        if (verb !== 'call') {
            return { resolvedKey: `__posthog_exec_${verb}__` }
        }

        const callMatch = rest.match(/^(?:--json\s+)?([a-zA-Z0-9_-]+)\s*([\s\S]*)$/)
        if (!callMatch) {
            return { resolvedKey: '__posthog_exec_unknown__' }
        }

        const innerToolName = callMatch[1]
        const jsonBody = (callMatch[2] ?? '').trim()
        let innerInput: Record<string, unknown> = {}
        if (jsonBody) {
            try {
                innerInput = JSON.parse(jsonBody)
            } catch {
                // Leave malformed payloads renderable as generic tool calls.
            }
        }
        return { resolvedKey: innerToolName, innerToolName, innerInput }
    }

    return { resolvedKey: toolName || claudeToolName || '' }
}

/** Resolves renderer-facing fields from a raw streamed tool invocation. */
export function resolveToolCall(toolCall: ResolvableToolCall): ResolvedToolCall {
    const claudeToolName = extractClaudeToolName(toolCall.meta)
    return {
        ...resolveToolKey(toolCall.rawServerName, toolCall.rawToolName, toolCall.input, claudeToolName),
        claudeToolName,
    }
}
