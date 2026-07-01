/**
 * Harness-mediated proxy for a large MCP connection: expose three helpers and
 * keep the full catalog in memory instead of inlining every tool's schema.
 *   - `<prefix>__explore_tools`   — list/search tools (names + descriptions).
 *   - `<prefix>__get_tool_schema` — fetch one tool's full input schema.
 *   - `<prefix>__call_tool`       — invoke a tool by its raw remote name.
 * Splitting search from schema-fetch (vs one overloaded tool) makes the
 * find → read-schema → call flow legible, so the model reads args instead of
 * guessing them. `exposed` is the deny/allowlist-filtered catalog; names outside
 * it are unreachable. The driver gates `call_tool` on the underlying tool (driver.ts).
 */

import type { AgentTool, AgentToolResult } from '@earendil-works/pi-agent-core'
import type { TSchema } from '@earendil-works/pi-ai'

import type { ToolResultDetails } from './build-agent-tools'
import type { OpenedMcp, RemoteMcpTool } from './mcp-clients'
import { PROXY_CALL_TOOL, PROXY_EXPLORE_TOOL, PROXY_GET_SCHEMA_TOOL } from './mcp-tool-lookup'

const EXPLORE_RESULT_CAP = 50

/** Cap for inlining a tool's input schema into a call_tool error. Small schemas
 *  ride along so the model can fix args in one retry; a large one would balloon
 *  the error, so we name explore_tools instead. ~500 tokens. */
const MAX_ERROR_SCHEMA_CHARS = 2_000

export interface McpProxyTools {
    tools: AgentTool<TSchema, ToolResultDetails>[]
    /** The driver keys its dynamic approval gate on this. */
    callToolName: string
    /** Pure resolver, captured so the driver's gate can mirror dispatch
     *  resolution exactly. See {@link resolveProxyRemoteName} for the rule. */
    resolveRemoteName: (raw: string) => string
}

/**
 * Map a `call_tool({tool_name})` arg to the actual remote name that will be
 * dispatched. The rule must match what `call_tool` does at execute time — the
 * driver's dynamic approval gate keys on `<prefix>__<resolved>`, and if it
 * resolves differently from dispatch, an `approve`-gated tool can run
 * unapproved. The precedence is:
 *
 *   1. raw exists in the exposed catalog → use it as-is. This is load-bearing
 *      for the collision case: a remote tool whose RAW name starts with
 *      `<prefix>__` (e.g. `big__delete` on the `big` server) must dispatch and
 *      gate as itself, not as the stripped `delete`.
 *   2. raw starts with our `<prefix>__` AND the stripped name exists → strip.
 *      This is the natural mistake-tolerance for the model, which sees tools
 *      as `<prefix>__<name>` and often passes that form back as `tool_name`.
 *   3. otherwise → return raw (dispatch will surface `unknown_tool`).
 */
export function resolveProxyRemoteName(raw: string, prefix: string, has: (name: string) => boolean): string {
    if (has(raw)) {
        return raw
    }
    const marker = `${prefix}__`
    if (raw.startsWith(marker)) {
        const stripped = raw.slice(marker.length)
        if (has(stripped)) {
            return stripped
        }
    }
    return raw
}

export function makeMcpProxyTools(client: OpenedMcp, exposed: RemoteMcpTool[]): McpProxyTools {
    const prefix = client.prefix
    const byName = new Map<string, RemoteMcpTool>(exposed.map((t) => [t.name, t]))
    const exploreName = `${prefix}__${PROXY_EXPLORE_TOOL}`
    const getSchemaName = `${prefix}__${PROXY_GET_SCHEMA_TOOL}`
    const callToolName = `${prefix}__${PROXY_CALL_TOOL}`

    const resolveRemoteName = (raw: string): string => resolveProxyRemoteName(raw, prefix, (n) => byName.has(n))

    const surfaceNote =
        `This server exposes ${exposed.length} tools on demand rather than inline. ` +
        `Use ${exploreName} to find a tool, ${getSchemaName} to read its input schema, ` +
        `then ${callToolName} to invoke it.`

    const exploreTool: AgentTool<TSchema, ToolResultDetails> = {
        name: exploreName,
        label: exploreName,
        description:
            `Find tools this MCP server exposes (${exposed.length} total). ${surfaceNote} ` +
            'Pass `query` to search names + descriptions (case-insensitive; multiple terms all must match; ' +
            'omit to list all). Returns names + descriptions only, no schemas — ' +
            `call ${getSchemaName} for a tool's arguments before invoking it.`,
        parameters: {
            type: 'object',
            properties: {
                query: {
                    type: 'string',
                    description: 'Terms to match against tool names + descriptions (case-insensitive; all must match).',
                },
            },
        } as unknown as TSchema,
        execute: async (_callId, args): Promise<AgentToolResult<ToolResultDetails>> => {
            const a = (args ?? {}) as { query?: unknown }
            // Tokenized AND-match: every whitespace-separated term must appear in
            // the name or description. A literal whole-string match made natural
            // multi-word queries ("agent-applications retrieve") return nothing,
            // since tool names are hyphenated — forcing a wasted re-query.
            const tokens = typeof a.query === 'string' ? a.query.trim().toLowerCase().split(/\s+/).filter(Boolean) : []
            const matches = tokens.length
                ? exposed.filter((t) => {
                      const hay = `${t.name} ${t.description}`.toLowerCase()
                      return tokens.every((tok) => hay.includes(tok))
                  })
                : exposed
            const results = matches
                .slice(0, EXPLORE_RESULT_CAP)
                .map((t) => ({ name: t.name, description: t.description }))
            const output = { total: matches.length, returned: results.length, tools: results }
            return { content: [{ type: 'text', text: JSON.stringify(output) }], details: { output } }
        },
    }

    const getSchemaTool: AgentTool<TSchema, ToolResultDetails> = {
        name: getSchemaName,
        label: getSchemaName,
        description:
            `Get one tool's full input schema (its exact argument names + types) before calling it with ${callToolName}. ` +
            `Find tool names via ${exploreName}. Always read the schema here rather than guessing arguments.`,
        parameters: {
            type: 'object',
            properties: {
                tool_name: { type: 'string', description: 'Raw remote tool name to fetch the input schema for.' },
            },
            required: ['tool_name'],
        } as unknown as TSchema,
        execute: async (_callId, args): Promise<AgentToolResult<ToolResultDetails>> => {
            const a = (args ?? {}) as { tool_name?: unknown }
            const toolName = resolveRemoteName(typeof a.tool_name === 'string' ? a.tool_name : '')
            const remote = byName.get(toolName)
            if (!remote) {
                throw new Error(`unknown_tool: ${toolName}`)
            }
            const output = { name: remote.name, description: remote.description, input_schema: remote.inputSchema }
            return { content: [{ type: 'text', text: JSON.stringify(output) }], details: { output } }
        },
    }

    const callTool: AgentTool<TSchema, ToolResultDetails> = {
        name: callToolName,
        label: callToolName,
        description:
            `Invoke a tool exposed by this MCP server. ${surfaceNote} ` +
            'Pass the raw tool name and its `arguments`. The argument names + types are NOT shown here — if you ' +
            `have not already read this tool's schema via ${getSchemaName} this session, do that FIRST and match ` +
            'it exactly. Never invent argument names.',
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
            const toolName = resolveRemoteName(typeof a.tool_name === 'string' ? a.tool_name : '')
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
                const base = firstText?.text ?? `mcp_tool_error: ${prefix}__${toolName}`
                // Point the model at the tool's input schema so a wrong-args
                // failure becomes a guided retry, not another guess (call_tool's
                // own `arguments` param carries no per-tool shape). Inline a small
                // schema for a one-shot fix; for a large one just name
                // explore_tools so the error can't balloon.
                const schema = JSON.stringify(byName.get(toolName)?.inputSchema ?? {})
                const hint =
                    schema.length <= MAX_ERROR_SCHEMA_CHARS
                        ? `Input schema for ${toolName}: ${schema}`
                        : `Call ${getSchemaName}({ tool_name: "${toolName}" }) for its full input schema.`
                throw new Error(`${base}\n${hint}`)
            }
            return { content: [{ type: 'text', text: JSON.stringify(result) }], details: { output: result } }
        },
    }

    return { tools: [exploreTool, getSchemaTool, callTool], callToolName, resolveRemoteName }
}
