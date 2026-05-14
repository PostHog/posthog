/**
 * Tool execution interface. Native-only in v1: every tool runs in-process inside the runner.
 * The plan calls for a Modal sandbox manager for custom tools later; that ships behind the
 * same interface so callers don't change.
 */
export interface ToolContext {
    readonly sessionId: string
    readonly teamId: number
    readonly applicationId: string | null
    readonly revisionId: string | null
    /** Decrypted secrets requested by the tool, fetched via the internal-API client. */
    readonly secrets: Record<string, string>
}

export interface ToolCall {
    readonly id: string
    readonly args: unknown
}

export type ToolResult =
    | { ok: true; value: unknown }
    | { ok: false; error: string }

export interface ToolHandler {
    readonly id: string
    invoke(call: ToolCall, ctx: ToolContext): Promise<ToolResult>
}
