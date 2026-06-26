/**
 * Harness-mediated proxy for a large MCP connection: expose two helpers and keep
 * the full catalog in memory instead of inlining every tool's schema.
 *   - `<prefix>__explore_tools` — list/search tools, or fetch one tool's schema.
 *   - `<prefix>__call_tool`     — invoke a tool by its raw remote name.
 * `exposed` is the deny/allowlist-filtered catalog; names outside it are
 * unreachable. The driver gates `call_tool` on the underlying tool (driver.ts).
 */

import type { AgentTool, AgentToolResult } from '@earendil-works/pi-agent-core'
import type { TSchema } from '@earendil-works/pi-ai'

import type { ToolResultDetails } from './build-agent-tools'
import type { OpenedMcp, RemoteMcpTool } from './mcp-clients'

const EXPLORE_RESULT_CAP = 50

export interface McpProxyTools {
    tools: AgentTool<TSchema, ToolResultDetails>[]
    /** The driver keys its dynamic approval gate on this. */
    callToolName: string
}

export function makeMcpProxyTools(client: OpenedMcp, exposed: RemoteMcpTool[]): McpProxyTools {
    const prefix = client.prefix
    const byName = new Map<string, RemoteMcpTool>(exposed.map((t) => [t.name, t]))
    const exploreName = `${prefix}__explore_tools`
    const callToolName = `${prefix}__call_tool`

    const surfaceNote =
        `This server exposes ${exposed.length} tools on demand rather than inline. ` +
        `Use ${exploreName} to find a tool (and fetch its input schema), then ${callToolName} to invoke it.`

    const exploreTool: AgentTool<TSchema, ToolResultDetails> = {
        name: exploreName,
        label: exploreName,
        description:
            `Explore the ${exposed.length} tools this MCP server exposes. ${surfaceNote} ` +
            'Pass `query` to search names + descriptions (case-insensitive substring; omit to list all) — ' +
            'returns names + descriptions only, no schemas, to stay cheap. ' +
            "Pass `tool_name` instead to fetch that one tool's full input schema before calling it.",
        parameters: {
            type: 'object',
            properties: {
                query: {
                    type: 'string',
                    description: 'Substring to match against tool names + descriptions (case-insensitive).',
                },
                tool_name: {
                    type: 'string',
                    description: 'Raw remote tool name to fetch the full input schema for.',
                },
            },
        } as unknown as TSchema,
        execute: async (_callId, args): Promise<AgentToolResult<ToolResultDetails>> => {
            const a = (args ?? {}) as { query?: unknown; tool_name?: unknown }
            if (typeof a.tool_name === 'string' && a.tool_name.length > 0) {
                const remote = byName.get(a.tool_name)
                if (!remote) {
                    throw new Error(`unknown_tool: ${a.tool_name}`)
                }
                const output = { name: remote.name, description: remote.description, input_schema: remote.inputSchema }
                return { content: [{ type: 'text', text: JSON.stringify(output) }], details: { output } }
            }
            const needle = typeof a.query === 'string' ? a.query.trim().toLowerCase() : ''
            const matches = needle
                ? exposed.filter(
                      (t) => t.name.toLowerCase().includes(needle) || t.description.toLowerCase().includes(needle)
                  )
                : exposed
            const results = matches
                .slice(0, EXPLORE_RESULT_CAP)
                .map((t) => ({ name: t.name, description: t.description }))
            const output = { total: matches.length, returned: results.length, tools: results }
            return { content: [{ type: 'text', text: JSON.stringify(output) }], details: { output } }
        },
    }

    const callTool: AgentTool<TSchema, ToolResultDetails> = {
        name: callToolName,
        label: callToolName,
        description:
            `Invoke a tool exposed by this MCP server. ${surfaceNote} ` +
            "Pass the raw tool name and its arguments (per explore_tools' input_schema).",
        parameters: {
            type: 'object',
            properties: {
                tool_name: { type: 'string', description: 'Raw remote tool name to invoke.' },
                arguments: { type: 'object', description: "Arguments object matching the tool's input schema." },
            },
            required: ['tool_name'],
        } as unknown as TSchema,
        execute: async (_callId, args): Promise<AgentToolResult<ToolResultDetails>> => {
            const a = (args ?? {}) as { tool_name?: unknown; arguments?: unknown }
            const toolName = typeof a.tool_name === 'string' ? a.tool_name : ''
            if (!byName.has(toolName)) {
                throw new Error(`unknown_tool: ${toolName}`)
            }
            const callArgs = (a.arguments ?? {}) as Record<string, unknown>
            const result = await client.callTool(toolName, callArgs)
            // Result-shaping mirrors makeMcpTool.
            if (result.isError) {
                const firstText = (result.content as Array<{ type: string; text?: string }>).find(
                    (c) => c.type === 'text' && typeof c.text === 'string'
                )
                throw new Error(firstText?.text ?? `mcp_tool_error: ${prefix}__${toolName}`)
            }
            return { content: [{ type: 'text', text: JSON.stringify(result) }], details: { output: result } }
        },
    }

    return { tools: [exploreTool, callTool], callToolName }
}
