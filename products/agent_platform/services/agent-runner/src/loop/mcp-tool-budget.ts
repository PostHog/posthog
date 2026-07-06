/**
 * Decide how an MCP connection's tools reach the model: listed inline, or behind
 * a proxy. Front-loading every tool's schema is fine for a small server but
 * overflows the model for a rich one (the PostHog MCP: 603 tools, ~2.7 MB), so
 * past a budget we expose a proxy (mcp-proxy.ts) instead and load schemas on demand.
 */
import type { RemoteMcpTool } from './mcp-clients'

export interface McpExposureBudget {
    maxInlineTools: number
    /** Serialized inline tool block (name + description + input schema), in chars. ~4 chars/token. */
    maxInlineChars: number
}

/** incident.io (38 tools, ~85k chars) stays inline; the PostHog MCP (603, ~2.7M) proxies. */
export const DEFAULT_MCP_EXPOSURE_BUDGET: McpExposureBudget = {
    maxInlineTools: 40,
    maxInlineChars: 100_000,
}

export interface McpExposureDecision {
    mode: 'inline' | 'proxy'
    toolCount: number
    serializedChars: number
    /** Which limit(s) forced the proxy — empty when inline. */
    reasons: string[]
}

export function serializedToolChars(tools: readonly RemoteMcpTool[]): number {
    let total = 0
    for (const t of tools) {
        total += t.name.length
        total += t.description?.length ?? 0
        total += JSON.stringify(t.inputSchema ?? {}).length
    }
    return total
}

/** Decide inline vs proxy for one connection's already-filtered tools. */
export function decideMcpExposure(
    tools: readonly RemoteMcpTool[],
    budget: McpExposureBudget = DEFAULT_MCP_EXPOSURE_BUDGET
): McpExposureDecision {
    const toolCount = tools.length
    const serializedChars = serializedToolChars(tools)
    const reasons: string[] = []
    if (toolCount > budget.maxInlineTools) {
        reasons.push(`tool_count ${toolCount} > ${budget.maxInlineTools}`)
    }
    if (serializedChars > budget.maxInlineChars) {
        reasons.push(`serialized_chars ${serializedChars} > ${budget.maxInlineChars}`)
    }
    return {
        mode: reasons.length > 0 ? 'proxy' : 'inline',
        toolCount,
        serializedChars,
        reasons,
    }
}
