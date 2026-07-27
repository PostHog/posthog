import { AgentSpec, AgentSpecSchema, McpRef } from '@posthog/agent-shared'

import { effectiveToolLevel, lookupMcpToolApproval, resolveApprovedExecutor } from './mcp-tool-lookup'

/**
 * Tests pass spec shapes in zod-input form (defaults omitted, partial
 * object entries). Routing the override through `AgentSpecSchema.parse`
 * fills in every default — that's the spec the runner actually sees.
 */
function buildSpec(overrides: Record<string, unknown> = {}): AgentSpec {
    return AgentSpecSchema.parse({ model: 'anthropic/claude-opus-4-7', ...overrides })
}

describe('lookupMcpToolApproval', () => {
    it('returns the policy when the exposed name resolves to an approve-level entry', () => {
        const spec = buildSpec({
            mcps: [
                {
                    kind: 'agent',
                    id: 'posthog',
                    url: 'https://app.posthog.com/api/mcp',
                    default_tool_approval: 'allow',
                    tools: [
                        {
                            name: 'agent-applications-revisions-promote-create',
                            level: 'approve',
                            approval_policy: { type: 'principal', ttl_ms: 900_000 },
                        },
                    ],
                },
            ],
        })
        const result = lookupMcpToolApproval('posthog__agent-applications-revisions-promote-create', spec)
        expect(result).not.toBeNull()
        expect(result?.requires_approval).toBe(true)
        expect(result?.approval_policy.type).toBe('principal')
        expect(result?.approval_policy.ttl_ms).toBe(900_000)
    })

    it('returns null when a tool takes an allow default (no gate)', () => {
        const spec = buildSpec({
            mcps: [
                {
                    kind: 'agent',
                    id: 'linear',
                    url: 'https://mcp.linear.app/sse',
                    default_tool_approval: 'allow',
                    tools: [{ name: 'create-issue', level: 'approve' }],
                },
            ],
        })
        // list-issues has no entry → takes the 'allow' default → no gate.
        expect(lookupMcpToolApproval('linear__list-issues', spec)).toBeNull()
    })

    it('returns null when no mcp prefix matches', () => {
        const spec = buildSpec({
            mcps: [
                { kind: 'agent', id: 'linear', url: 'https://mcp.linear.app/sse', default_tool_approval: 'approve' },
            ],
        })
        expect(lookupMcpToolApproval('github__create-issue', spec)).toBeNull()
    })

    it.each([
        // No separator → caller is asking about a native/custom/client tool, not an MCP one.
        '@posthog/team-delete',
        'web_fetch',
        // Leading or trailing separator → degenerate; not a real prefix__remote name.
        '__only-remote',
        'only-prefix__',
        // Empty string is meaningless.
        '',
    ])('returns null for non-MCP-shaped names like %s', (name) => {
        const spec = buildSpec({
            mcps: [
                { kind: 'agent', id: 'linear', url: 'https://mcp.linear.app/sse', default_tool_approval: 'approve' },
            ],
        })
        expect(lookupMcpToolApproval(name, spec)).toBeNull()
    })

    it('handles remote names that contain the `__` separator themselves', () => {
        // Defensive: a remote MCP might name a tool `parent__child`. The
        // helper picks the FIRST `__` as the prefix boundary, leaving
        // `parent__child` as the remote name. Authors who hit this collision
        // need to rename one side — but the lookup mustn't silently mis-route.
        const spec = buildSpec({
            mcps: [
                {
                    kind: 'agent',
                    id: 'service',
                    url: 'https://example.com/mcp',
                    default_tool_approval: 'allow',
                    tools: [{ name: 'parent__child', level: 'approve' }],
                },
            ],
        })
        expect(lookupMcpToolApproval('service__parent__child', spec)).not.toBeNull()
    })

    it('only checks against ref.tools[]; ignores tools listed in spec.tools[]', () => {
        // A native tool with the same id as a remote MCP tool is a separate
        // declaration — the lookup must not cross-pollinate. Belt-and-braces
        // alongside the dispatcher's collision skip.
        const spec = buildSpec({
            tools: [
                {
                    kind: 'native',
                    id: 'linear__create-issue',
                    requires_approval: true,
                    approval_policy: { type: 'agent' },
                },
            ],
            mcps: [
                {
                    kind: 'agent',
                    id: 'linear',
                    url: 'https://mcp.linear.app/sse',
                    // create-issue takes the 'allow' default → no MCP-side gate.
                    default_tool_approval: 'allow',
                },
            ],
        })
        // Even though `spec.tools[]` declares the same id, the lookup
        // resolves through `spec.mcps[]` only — and create-issue takes the allow default.
        expect(lookupMcpToolApproval('linear__create-issue', spec)).toBeNull()
    })
})

describe('effectiveToolLevel (default + per-tool override model)', () => {
    const refOf = (mcp: Record<string, unknown>): McpRef => buildSpec({ mcps: [mcp] }).mcps[0]

    it('returns the connection default when there is no per-tool override', () => {
        const ref = refOf({
            kind: 'agent',
            id: 'demo',
            url: 'https://example.com/mcp',
            default_tool_approval: 'approve',
        })
        expect(effectiveToolLevel(ref, 'anything')).toBe('approve')
    })

    it('a per-tool level overrides the default for that tool only', () => {
        const ref = refOf({
            kind: 'agent',
            id: 'demo',
            url: 'https://example.com/mcp',
            default_tool_approval: 'approve',
            tools: [
                { name: 'safe', level: 'allow' },
                { name: 'danger', level: 'deny' },
            ],
        })
        expect(effectiveToolLevel(ref, 'safe')).toBe('allow')
        expect(effectiveToolLevel(ref, 'danger')).toBe('deny')
        // A tool with no override falls back to the default.
        expect(effectiveToolLevel(ref, 'other')).toBe('approve')
    })
})

describe('lookupMcpToolApproval (default + per-tool override model)', () => {
    it('gates an approve-level tool, falling back to the principal/24h default policy', () => {
        const spec = buildSpec({
            mcps: [{ kind: 'agent', id: 'demo', url: 'https://example.com/mcp', default_tool_approval: 'approve' }],
        })
        const result = lookupMcpToolApproval('demo__promote', spec)
        expect(result).not.toBeNull()
        expect(result?.requires_approval).toBe(true)
        expect(result?.approval_policy.type).toBe('principal')
        expect(result?.approval_policy.ttl_ms).toBe(24 * 60 * 60 * 1000)
    })

    it('uses the ref-level approval_policy for approve-level tools when set', () => {
        const spec = buildSpec({
            mcps: [
                {
                    kind: 'agent',
                    id: 'demo',
                    url: 'https://example.com/mcp',
                    default_tool_approval: 'approve',
                    approval_policy: { type: 'agent', ttl_ms: 900_000 },
                },
            ],
        })
        const result = lookupMcpToolApproval('demo__promote', spec)
        expect(result?.requires_approval).toBe(true)
        expect(result?.approval_policy.type).toBe('agent')
        expect(result?.approval_policy.ttl_ms).toBe(900_000)
    })

    it('does NOT gate allow-level tools (default or override)', () => {
        const allowDefault = buildSpec({
            mcps: [{ kind: 'agent', id: 'demo', url: 'https://example.com/mcp', default_tool_approval: 'allow' }],
        })
        expect(lookupMcpToolApproval('demo__echo', allowDefault)).toBeNull()

        const allowOverride = buildSpec({
            mcps: [
                {
                    kind: 'agent',
                    id: 'demo',
                    url: 'https://example.com/mcp',
                    default_tool_approval: 'approve',
                    tools: [{ name: 'echo', level: 'allow' }],
                },
            ],
        })
        // The override wins: this tool is auto-allow even though the default is approve.
        expect(lookupMcpToolApproval('demo__echo', allowOverride)).toBeNull()
    })

    it('an approve override on an allow-default ref gates that one tool', () => {
        const spec = buildSpec({
            mcps: [
                {
                    kind: 'agent',
                    id: 'demo',
                    url: 'https://example.com/mcp',
                    default_tool_approval: 'allow',
                    tools: [{ name: 'promote', level: 'approve' }],
                },
            ],
        })
        expect(lookupMcpToolApproval('demo__echo', spec)).toBeNull() // default allow
        expect(lookupMcpToolApproval('demo__promote', spec)?.requires_approval).toBe(true)
    })

    it('returns null for deny-level tools (they are never exposed, so dispatch never asks)', () => {
        const spec = buildSpec({
            mcps: [{ kind: 'agent', id: 'demo', url: 'https://example.com/mcp', default_tool_approval: 'deny' }],
        })
        expect(lookupMcpToolApproval('demo__echo', spec)).toBeNull()
    })

    it('gates a real remote tool that merely shares a proxy-helper name (no blanket name exemption)', () => {
        // Regression for veria-ai's finding: the lookup used to return null for
        // ANY tool named call_tool / explore_tools / get_tool_schema, so a real
        // remote tool with one of those names on a NON-proxied connection ran
        // inline without approval under an `approve` default. The lookup is now a
        // pure level check — the synthetic-proxy-helper exemption is proxy-aware
        // and lives in the driver (which knows which connections are proxied),
        // not here, so a real same-named tool is gated like any other.
        const spec = buildSpec({
            mcps: [{ kind: 'agent', id: 'small', url: 'https://example.com/mcp', default_tool_approval: 'approve' }],
        })
        expect(lookupMcpToolApproval('small__call_tool', spec)?.requires_approval).toBe(true)
        expect(lookupMcpToolApproval('small__explore_tools', spec)?.requires_approval).toBe(true)
        expect(lookupMcpToolApproval('small__get_tool_schema', spec)?.requires_approval).toBe(true)
    })
})

describe('resolveApprovedExecutor (resume dispatch)', () => {
    // The driver builds `realExecute` from the live tool surface; for a proxied
    // connection that's only `<prefix>__call_tool` + `<prefix>__explore_tools`,
    // NOT the per-remote names the approval gate keys on.
    const execs = new Map<string, string>([
        ['@posthog/query', 'native-exec'],
        ['posthog__call_tool', 'call-tool-exec'],
        ['posthog__explore_tools', 'explore-exec'],
    ])
    const proxyCallTools = new Map<string, unknown>([['posthog__call_tool', {}]])

    it('resolves a native/inline tool by its exact name', () => {
        expect(resolveApprovedExecutor('@posthog/query', execs, proxyCallTools)).toBe('native-exec')
    })

    it('resolves a proxy-routed row (<prefix>__<remote>) to the connection call_tool executor', () => {
        // The bug: a plain lookup misses the row's re-keyed name, dropping the
        // approved call. The fallback recovers the call_tool executor (whose
        // args are the row's stored call_tool args).
        expect(execs.get('posthog__get-insights')).toBeUndefined() // <- what the driver used to do
        expect(resolveApprovedExecutor('posthog__get-insights', execs, proxyCallTools)).toBe('call-tool-exec')
    })

    it('returns undefined for an unknown tool with no proxied prefix', () => {
        expect(resolveApprovedExecutor('linear__create-issue', execs, proxyCallTools)).toBeUndefined()
    })
})
