import { z } from 'zod'

import {
    AgentRevision,
    AgentSession,
    AgentSpecSchema,
    EMPTY_USAGE_TOTAL,
    HttpClient,
    McpRef,
    ToolRefSchema,
} from '@posthog/agent-shared'

import { AgentToolDeps, buildAgentTools } from './build-agent-tools'
import type { OpenedMcp, RemoteMcpTool } from './mcp-clients'

type ToolRefInput = z.input<typeof ToolRefSchema>

/**
 * Parse the spec from raw input (mirroring `build-agent-tools.test.ts`) so the
 * `mcps[]` come back fully defaulted — object-form `tools[]` entries need
 * `requires_approval`/`approval_policy` defaults applied, which only the schema
 * does. `mcpInput` is the raw McpRef input shape (loose) rather than the strict
 * output `McpRef`.
 */
function makeRev(toolRefs: ToolRefInput[] = [], mcpInput: Record<string, unknown>[] = []): AgentRevision {
    return {
        id: 'rev1',
        application_id: 'app1',
        parent_revision_id: null,
        created_by_id: null,
        created_at: '2026-06-26',
        state: 'live',
        bundle_uri: 's3://',
        bundle_sha256: null,
        spec: AgentSpecSchema.parse({ model: 'test/x', tools: toolRefs, skills: [], mcps: mcpInput }),
        encrypted_env: null,
    }
}

function makeSession(): AgentSession {
    return {
        id: 's1',
        application_id: 'app1',
        revision_id: 'rev1',
        team_id: 1,
        external_key: null,
        idempotency_key: null,
        trigger_metadata: null,
        state: 'running',
        principal: { kind: 'posthog', user_id: 'u1', team_id: 1 },
        conversation: [],
        pending_inputs: [],
        retry_count: 0,
        acl: [],
        pending_elevation_requests: [],
        usage_total: { ...EMPTY_USAGE_TOTAL },
        created_at: '2026-06-26',
        updated_at: '2026-06-26',
    }
}

function makeDeps(rev: AgentRevision, over: Partial<AgentToolDeps> = {}): AgentToolDeps {
    return {
        rev,
        session: makeSession(),
        sandbox: null,
        secrets: {},
        // Bundle is never touched on these MCP-only paths (no custom tools).
        bundle: null as unknown as AgentToolDeps['bundle'],
        log: () => undefined,
        http: new HttpClient(),
        posthogApiBaseUrl: 'http://localhost:8010',
        ...over,
    }
}

/** In-process tool table the fake client serves — `inputSchema` is optional
 *  (defaults to `{ type: 'object' }`), matching `makeFakeMcp` below. */
type Handlers = Record<
    string,
    { description: string; inputSchema?: unknown; handler: (args: Record<string, unknown>) => Promise<unknown> }
>

/**
 * Stub `OpenedMcp` over an in-process tool table — mirrors the harness in
 * `build-agent-tools.test.ts`. `calls` records every `callTool` dispatch so we
 * can assert the proxy routes through the real client.
 */
function makeFakeMcp(
    prefix: string,
    ref: McpRef,
    handlers: Handlers
): OpenedMcp & { calls: Array<{ name: string; args: Record<string, unknown> }> } {
    const calls: Array<{ name: string; args: Record<string, unknown> }> = []
    return {
        prefix,
        ref,
        listTools: async () => {
            const out: RemoteMcpTool[] = []
            for (const [name, h] of Object.entries(handlers)) {
                out.push({ name, description: h.description, inputSchema: h.inputSchema ?? { type: 'object' } })
            }
            return out
        },
        callTool: async (name, args) => {
            calls.push({ name, args })
            const h = handlers[name]
            if (!h) {
                return { content: [{ type: 'text' as const, text: `unknown_tool: ${name}` }], isError: true }
            }
            try {
                const result = await h.handler(args)
                return {
                    content: [{ type: 'text' as const, text: JSON.stringify(result) }],
                    structuredContent: result as Record<string, unknown>,
                }
            } catch (err) {
                return { content: [{ type: 'text' as const, text: (err as Error).message }], isError: true }
            }
        },
        close: async () => undefined,
        calls,
    }
}

/** Build N fake handlers `tool-0..tool-(n-1)`, each echoing its args. */
function manyHandlers(n: number): Handlers {
    const out: Handlers = {}
    for (let i = 0; i < n; i++) {
        out[`tool-${i}`] = handler(`Tool number ${i}.`)
    }
    return out
}

function handler(description: string, inputSchema?: unknown): Handlers[string] {
    return { description, inputSchema, handler: async (args: Record<string, unknown>) => ({ echoed: args }) }
}

function byLabel(
    built: Awaited<ReturnType<typeof buildAgentTools>>,
    label: string
): Awaited<ReturnType<typeof buildAgentTools>>['tools'][number] {
    const tool = built.tools.find((t) => t.label === label)
    if (!tool) {
        throw new Error(`tool ${label} not built`)
    }
    return tool
}

describe('mcp proxy exposure', () => {
    it('proxies a large connection: three helper tools, no inline tools, populates mcpProxyCallTools', async () => {
        const rev = makeRev(
            [],
            [
                {
                    kind: 'agent',
                    id: 'posthog',
                    url: 'https://example.com/mcp',
                    secrets: [],
                    default_tool_approval: 'allow',
                },
            ]
        )
        const mcp = makeFakeMcp('posthog', rev.spec.mcps[0], manyHandlers(60))
        const built = await buildAgentTools(rev, makeDeps(rev, { mcpClients: [mcp] }))

        const labels = built.tools.map((t) => t.label)
        // Exactly the three proxy helpers — none of the 60 inline tools.
        expect(labels).toContain('posthog__explore_tools')
        expect(labels).toContain('posthog__get_tool_schema')
        expect(labels).toContain('posthog__call_tool')
        expect(labels).not.toContain('posthog__tool-0')
        expect(labels.filter((l) => l.startsWith('posthog__'))).toHaveLength(3)

        // The dispatcher is recorded so the driver can install its dynamic gate.
        expect([...built.mcpProxyCallTools.keys()]).toEqual(['posthog__call_tool'])
        const entry = built.mcpProxyCallTools.get('posthog__call_tool')
        expect(entry?.client).toBe(mcp)
        // The same resolver the proxy uses at dispatch must travel through to
        // the driver's gate — otherwise the gate keys on a different name
        // than dispatch and an `approve` tool can run unapproved.
        expect(typeof entry?.resolveRemoteName).toBe('function')
    })

    it('inlines a small connection: one tool per remote, no proxy helpers', async () => {
        const rev = makeRev(
            [],
            [
                {
                    kind: 'agent',
                    id: 'linear',
                    url: 'https://example.com/linear',
                    secrets: [],
                    default_tool_approval: 'allow',
                },
            ]
        )
        const mcp = makeFakeMcp('linear', rev.spec.mcps[0], {
            'create-issue': handler('Open a new Linear issue.'),
            'list-issues': handler('List recent Linear issues.'),
        })
        const built = await buildAgentTools(rev, makeDeps(rev, { mcpClients: [mcp] }))

        const labels = built.tools.map((t) => t.label)
        expect(labels).toContain('linear__create-issue')
        expect(labels).toContain('linear__list-issues')
        expect(labels).not.toContain('linear__explore_tools')
        expect(labels).not.toContain('linear__get_tool_schema')
        expect(labels).not.toContain('linear__call_tool')
        expect(built.mcpProxyCallTools.size).toBe(0)
    })

    describe('explore_tools + get_tool_schema', () => {
        async function buildProxy(): Promise<{
            built: Awaited<ReturnType<typeof buildAgentTools>>
            mcp: ReturnType<typeof makeFakeMcp>
        }> {
            const handlers = manyHandlers(60)
            handlers['get-insights'] = handler('Fetch insights for a project.', {
                type: 'object',
                properties: { project_id: { type: 'number' } },
                required: ['project_id'],
            })
            const rev = makeRev(
                [],
                [
                    {
                        kind: 'agent',
                        id: 'posthog',
                        url: 'https://example.com/mcp',
                        secrets: [],
                        default_tool_approval: 'allow',
                    },
                ]
            )
            const mcp = makeFakeMcp('posthog', rev.spec.mcps[0], handlers)
            const built = await buildAgentTools(rev, makeDeps(rev, { mcpClients: [mcp] }))
            return { built, mcp }
        }

        it('filters by query, returning names + descriptions only (no schemas), capped at 50', async () => {
            const { built } = await buildProxy()
            const res = await byLabel(built, 'posthog__explore_tools').execute('c1', { query: 'insights' })
            const out = res.details.output as { total: number; returned: number; tools: Array<Record<string, unknown>> }
            expect(out.total).toBe(1)
            expect(out.tools).toEqual([{ name: 'get-insights', description: 'Fetch insights for a project.' }])
            // No schema leaks into a query result.
            expect(out.tools[0]).not.toHaveProperty('input_schema')
        })

        it('matches a multi-word query when every term appears (not a literal whole-string substring)', async () => {
            // Real footgun: a natural query like "insights project" used to be
            // matched as one literal substring and returned 0, forcing a re-query.
            // Tokenized AND-match finds the tool.
            const { built } = await buildProxy()
            const res = await byLabel(built, 'posthog__explore_tools').execute('c1', { query: 'insights project' })
            const out = res.details.output as { total: number; tools: Array<{ name: string }> }
            expect(out.total).toBe(1)
            expect(out.tools[0].name).toBe('get-insights')
        })

        it('caps a broad match at 50 while reporting the true total', async () => {
            const { built } = await buildProxy()
            // "tool" matches all 60 `tool-N` entries.
            const res = await byLabel(built, 'posthog__explore_tools').execute('c1', { query: 'tool' })
            const out = res.details.output as { total: number; returned: number; tools: unknown[] }
            expect(out.total).toBe(60)
            expect(out.returned).toBe(50)
            expect(out.tools).toHaveLength(50)
        })

        it('get_tool_schema returns one tool full input schema', async () => {
            const { built } = await buildProxy()
            const res = await byLabel(built, 'posthog__get_tool_schema').execute('c1', { tool_name: 'get-insights' })
            expect(res.details.output).toEqual({
                name: 'get-insights',
                description: 'Fetch insights for a project.',
                input_schema: {
                    type: 'object',
                    properties: { project_id: { type: 'number' } },
                    required: ['project_id'],
                },
            })
        })

        it('get_tool_schema throws on an unknown tool_name', async () => {
            const { built } = await buildProxy()
            await expect(
                byLabel(built, 'posthog__get_tool_schema').execute('c1', { tool_name: 'nope' })
            ).rejects.toThrow(/unknown_tool: nope/)
        })

        it('explore_tools ignores tool_name (schema fetch moved to get_tool_schema) and lists instead', async () => {
            // Defensive: a stray tool_name on explore_tools must not 0-out the
            // list — it's a search tool now, so it returns the catalog.
            const { built } = await buildProxy()
            const res = await byLabel(built, 'posthog__explore_tools').execute('c1', { tool_name: 'get-insights' })
            const out = res.details.output as { total: number }
            expect(out.total).toBeGreaterThan(0)
        })
    })

    describe('call_tool', () => {
        it('dispatches the raw remote tool through the open client', async () => {
            const rev = makeRev(
                [],
                [
                    {
                        kind: 'agent',
                        id: 'posthog',
                        url: 'https://example.com/mcp',
                        secrets: [],
                        default_tool_approval: 'allow',
                    },
                ]
            )
            const mcp = makeFakeMcp('posthog', rev.spec.mcps[0], manyHandlers(60))
            const built = await buildAgentTools(rev, makeDeps(rev, { mcpClients: [mcp] }))

            const res = await byLabel(built, 'posthog__call_tool').execute('c1', {
                tool_name: 'tool-3',
                arguments: { q: 'hi' },
            })
            // Routed under the RAW remote name (no prefix), with the args passed through.
            expect(mcp.calls).toEqual([{ name: 'tool-3', args: { q: 'hi' } }])
            expect(res.details.output).toMatchObject({ structuredContent: { echoed: { q: 'hi' } } })
        })

        it('accepts a prefixed tool_name (strips its own prefix) — the model passes the name it sees', async () => {
            // The model only ever sees `<prefix>__<name>`, so passing that as
            // tool_name is the natural mistake (and what the agent.md references).
            // call_tool tolerates it instead of erroring unknown_tool.
            const rev = makeRev(
                [],
                [
                    {
                        kind: 'agent',
                        id: 'posthog',
                        url: 'https://example.com/mcp',
                        secrets: [],
                        default_tool_approval: 'allow',
                    },
                ]
            )
            const mcp = makeFakeMcp('posthog', rev.spec.mcps[0], manyHandlers(60))
            const built = await buildAgentTools(rev, makeDeps(rev, { mcpClients: [mcp] }))
            await byLabel(built, 'posthog__call_tool').execute('c1', {
                tool_name: 'posthog__tool-3',
                arguments: { q: 'hi' },
            })
            expect(mcp.calls).toEqual([{ name: 'tool-3', args: { q: 'hi' } }])
        })

        it('refuses a tool outside the exposed set (e.g. a denied one)', async () => {
            // `default_tool_approval: deny` + a single `allow` override = strict
            // allowlist; only `tool-0` is exposed. The dispatcher must refuse
            // `tool-1` even though it exists on the server.
            const rev = makeRev(
                [],
                [
                    {
                        kind: 'agent',
                        id: 'posthog',
                        url: 'https://example.com/mcp',
                        secrets: [],
                        default_tool_approval: 'deny',
                        tools: [{ name: 'tool-0', level: 'allow' }],
                    },
                ]
            )
            // 60 handlers so the (single allowed) connection still proxies via
            // the chars budget — but exposure is filtered to just `tool-0`.
            const handlers = manyHandlers(60)
            // Pad the one exposed tool's description so the (filtered) one-tool
            // catalog still trips the proxy budget by serialized size.
            handlers['tool-0'] = handler('x'.repeat(200_000))
            const mcp = makeFakeMcp('posthog', rev.spec.mcps[0], handlers)
            const built = await buildAgentTools(rev, makeDeps(rev, { mcpClients: [mcp] }))

            const callTool = byLabel(built, 'posthog__call_tool')
            // Allowed tool dispatches.
            await callTool.execute('c1', { tool_name: 'tool-0', arguments: {} })
            expect(mcp.calls.map((c) => c.name)).toEqual(['tool-0'])
            // Denied tool is unreachable — refused before any dispatch.
            await expect(callTool.execute('c2', { tool_name: 'tool-1', arguments: {} })).rejects.toThrow(
                /unknown_tool: tool-1/
            )
            expect(mcp.calls.map((c) => c.name)).toEqual(['tool-0'])
        })

        it('surfaces a remote isError as a thrown error', async () => {
            const rev = makeRev(
                [],
                [
                    {
                        kind: 'agent',
                        id: 'posthog',
                        url: 'https://example.com/mcp',
                        secrets: [],
                        default_tool_approval: 'allow',
                    },
                ]
            )
            const handlers = manyHandlers(60)
            handlers['tool-5'] = {
                description: 'boom',
                handler: async () => {
                    throw new Error('remote_blew_up')
                },
            }
            const mcp = makeFakeMcp('posthog', rev.spec.mcps[0], handlers)
            const built = await buildAgentTools(rev, makeDeps(rev, { mcpClients: [mcp] }))
            await expect(
                byLabel(built, 'posthog__call_tool').execute('c1', { tool_name: 'tool-5', arguments: {} })
            ).rejects.toThrow('remote_blew_up')
        })

        it('appends the tool input_schema to a call_tool error so the retry is schema-informed', async () => {
            // In proxy mode the model only sees call_tool's free-form `arguments`,
            // so a wrong-args call is easy. Handing it the schema on failure turns
            // "wrong args multiple times" into a one-shot, guided retry.
            const rev = makeRev(
                [],
                [
                    {
                        kind: 'agent',
                        id: 'posthog',
                        url: 'https://example.com/mcp',
                        secrets: [],
                        default_tool_approval: 'allow',
                    },
                ]
            )
            const handlers = manyHandlers(60)
            handlers['get-insights'] = {
                description: 'Fetch insights.',
                inputSchema: {
                    type: 'object',
                    properties: { project_id: { type: 'number' } },
                    required: ['project_id'],
                },
                handler: async () => {
                    throw new Error('missing required arg: project_id')
                },
            }
            const mcp = makeFakeMcp('posthog', rev.spec.mcps[0], handlers)
            const built = await buildAgentTools(rev, makeDeps(rev, { mcpClients: [mcp] }))

            let err: Error | undefined
            try {
                await byLabel(built, 'posthog__call_tool').execute('c1', { tool_name: 'get-insights', arguments: {} })
            } catch (e) {
                err = e as Error
            }
            expect(err?.message).toContain('missing required arg: project_id') // remote message preserved
            expect(err?.message).toContain('"required":["project_id"]') // + the schema, for a guided retry
        })

        it('names explore_tools instead of dumping a large schema into the error', async () => {
            // A big schema would balloon the error, so the cap swaps the inline
            // dump for a one-line pointer to get_tool_schema.
            const bigSchema = {
                type: 'object',
                properties: Object.fromEntries(
                    Array.from({ length: 200 }, (_, i) => [
                        `field_${i}`,
                        { type: 'string', description: 'x'.repeat(50) },
                    ])
                ),
            }
            const rev = makeRev(
                [],
                [
                    {
                        kind: 'agent',
                        id: 'posthog',
                        url: 'https://example.com/mcp',
                        secrets: [],
                        default_tool_approval: 'allow',
                    },
                ]
            )
            const handlers = manyHandlers(60)
            handlers['huge-tool'] = {
                description: 'has a big schema',
                inputSchema: bigSchema,
                handler: async () => {
                    throw new Error('bad args')
                },
            }
            const mcp = makeFakeMcp('posthog', rev.spec.mcps[0], handlers)
            const built = await buildAgentTools(rev, makeDeps(rev, { mcpClients: [mcp] }))

            let err: Error | undefined
            try {
                await byLabel(built, 'posthog__call_tool').execute('c1', { tool_name: 'huge-tool', arguments: {} })
            } catch (e) {
                err = e as Error
            }
            expect(err?.message).toContain('bad args')
            expect(err?.message).toContain('posthog__get_tool_schema({ tool_name: "huge-tool" })')
            // The giant schema is NOT inlined.
            expect(err?.message).not.toContain('field_199')
            expect(err!.message.length).toBeLessThan(2_000)
        })
    })
})
