/**
 * Worst-case fixture for the outbound-name rewrite. Locks in that every
 * tool-id-bearing field gets sanitized in one pass:
 *
 *   - tool declarations (`context.tools[].name`)
 *   - historical assistant tool calls (`messages[].content[].name`)
 *   - historical tool results (`messages[].toolName`)
 *
 * If a future pi-ai version starts validating a new field carrying a tool
 * id, the regression surfaces here first — the test fails on a sentinel
 * `@posthog/x` leaking through into the outbound payload — instead of
 * silently leaking a 400 to the next caller running on a strict provider.
 *
 * Also covers the inverse: `translateAssistantNamesBack` maps the
 * provider's echoed-back safe form to the original id the loop matches.
 */
import type { AssistantMessage, Message } from '@earendil-works/pi-ai'

import { sanitizeOutboundContext, translateAssistantNamesBack } from './driver'

const ORIGINAL = '@posthog/query'

// All known tool-id-bearing sites in a single fixture. Each value uses the
// `@posthog/` prefix; after sanitization, none should remain in the JSON
// stringified outbound context.
const fixtureContext = {
    systemPrompt: 'you are a bot',
    tools: [
        {
            name: ORIGINAL,
            description: 'run a query',
            parameters: { type: 'object' as const, properties: {} },
        },
    ],
    messages: [
        // Fresh user turn.
        { role: 'user', content: 'run it', timestamp: 1 } as unknown as Message,
        // Historical assistant tool call — `content[].name` carries the id.
        {
            role: 'assistant',
            content: [
                { type: 'text', text: 'on it' },
                { type: 'toolCall', id: 'call_1', name: ORIGINAL, arguments: { q: 'select 1' } },
            ],
            api: 'openai-completions',
            model: 'openai/gpt-4o',
            provider: 'openai',
            stopReason: 'toolUse',
            timestamp: 2,
        } as unknown as Message,
        // Paired tool result — `toolName` carries the id.
        {
            role: 'toolResult',
            toolCallId: 'call_1',
            toolName: ORIGINAL,
            content: [{ type: 'text', text: '{"rows":[]}' }],
            isError: false,
            timestamp: 3,
        } as unknown as Message,
    ],
}

describe('sanitizeOutboundContext (worst-case fixture)', () => {
    it('rewrites tool declarations to the provider-safe form', () => {
        const out = sanitizeOutboundContext(fixtureContext)
        expect(out.tools?.[0].name).not.toBe(ORIGINAL)
        expect(out.tools?.[0].name).toMatch(/^[a-zA-Z0-9_-]+$/)
    })

    it('rewrites historical assistant toolCall names', () => {
        const out = sanitizeOutboundContext(fixtureContext)
        const assistant = out.messages?.[1] as unknown as { content: Array<{ type: string; name?: string }> }
        const call = assistant.content.find((b) => b.type === 'toolCall')
        expect(call?.name).not.toBe(ORIGINAL)
        expect(call?.name).toMatch(/^[a-zA-Z0-9_-]+$/)
    })

    it('rewrites historical toolResult.toolName', () => {
        const out = sanitizeOutboundContext(fixtureContext)
        const result = out.messages?.[2] as unknown as { toolName?: string }
        expect(result.toolName).not.toBe(ORIGINAL)
        expect(result.toolName).toMatch(/^[a-zA-Z0-9_-]+$/)
    })

    it('leaves the original `@posthog/` shape nowhere in the serialised outbound payload', () => {
        // The single load-bearing assertion of the suite: if anyone adds a
        // new tool-id-bearing field upstream and forgets to wire it into
        // sanitizeOutboundContext, the original id leaks through here.
        const out = sanitizeOutboundContext(fixtureContext)
        expect(JSON.stringify(out)).not.toContain(ORIGINAL)
    })

    it('preserves message roles, ids, and non-name fields unchanged', () => {
        const out = sanitizeOutboundContext(fixtureContext)
        expect(out.messages?.[0]).toMatchObject({ role: 'user', content: 'run it' })
        const assistant = out.messages?.[1] as unknown as {
            role: string
            model: string
            content: Array<{ type: string; id?: string }>
        }
        expect(assistant.role).toBe('assistant')
        expect(assistant.model).toBe('openai/gpt-4o')
        expect(assistant.content.find((b) => b.type === 'toolCall')?.id).toBe('call_1')
    })

    it('leaves MCP-prefixed names <prefix>__<toolname> unchanged through sanitization', () => {
        // The runtime-mcps surface produces tool names like `linear__create-issue`.
        // Every character in that pattern (lowercase, `_`, `-`) is already in
        // the safe charset, so the sanitizer must be idempotent here — if a
        // future change accidentally widens what gets rewritten, this fails
        // and we catch it before MCP tool calls start echoing mangled names.
        const MCP_ORIGINAL = 'linear__create-issue'
        const out = sanitizeOutboundContext({
            systemPrompt: 'mcp test',
            tools: [
                {
                    name: MCP_ORIGINAL,
                    description: 'create a Linear issue',
                    parameters: { type: 'object' as const, properties: {} },
                },
            ],
            messages: [
                {
                    role: 'assistant',
                    content: [{ type: 'toolCall', id: 'call_m', name: MCP_ORIGINAL, arguments: {} }],
                    api: 'openai-completions',
                    model: 'openai/gpt-4o',
                    provider: 'openai',
                    stopReason: 'toolUse',
                    timestamp: 1,
                } as unknown as Message,
                {
                    role: 'toolResult',
                    toolCallId: 'call_m',
                    toolName: MCP_ORIGINAL,
                    content: [{ type: 'text', text: '{}' }],
                    isError: false,
                    timestamp: 2,
                } as unknown as Message,
            ],
        })
        expect(out.tools?.[0].name).toBe(MCP_ORIGINAL)
        const call = (out.messages?.[0] as unknown as { content: Array<{ name?: string }> }).content[0]
        expect(call.name).toBe(MCP_ORIGINAL)
        expect((out.messages?.[1] as unknown as { toolName?: string }).toolName).toBe(MCP_ORIGINAL)
    })

    it('leaves non-tool messages untouched (defensive)', () => {
        const out = sanitizeOutboundContext({
            systemPrompt: '',
            tools: [],
            messages: [{ role: 'user', content: 'plain', timestamp: 0 } as unknown as Message],
        })
        expect(out.messages?.[0]).toMatchObject({ role: 'user', content: 'plain' })
    })

    it('returns an object even when tools / messages are absent', () => {
        const out = sanitizeOutboundContext({ systemPrompt: 'x' } as Parameters<typeof sanitizeOutboundContext>[0])
        // tools / messages stay undefined; system stays untouched.
        expect(out).toEqual({ systemPrompt: 'x', tools: undefined, messages: undefined })
    })
})

describe('translateAssistantNamesBack', () => {
    it('maps the provider-safe form back to the original id', () => {
        const safeToOriginal = new Map([['posthog_query', '@posthog/query']])
        const out = translateAssistantNamesBack(
            {
                role: 'assistant',
                content: [
                    { type: 'text', text: 'sure' } as unknown,
                    { type: 'toolCall', id: 'call_1', name: 'posthog_query', arguments: {} } as unknown,
                ],
                api: 'openai-completions',
                model: 'openai/gpt-4o',
                provider: 'openai',
                stopReason: 'toolUse',
                timestamp: Date.now(),
                usage: { input: 0, output: 0, totalTokens: 0, cacheRead: 0, cacheWrite: 0, cost: {} },
            } as unknown as AssistantMessage,
            safeToOriginal
        )
        const call = out.content.find((b) => b.type === 'toolCall') as { name: string }
        expect(call.name).toBe('@posthog/query')
    })

    it('maps an MCP-prefixed safe name back to itself (identity)', () => {
        // The safe form == the original for `<prefix>__<remoteName>` patterns,
        // but the lookup is still keyed by the safe form so a future change
        // to provider-safe-names that introduces a transform won't strand
        // MCP tools without a mapping.
        const MCP_ID = 'linear__create-issue'
        const safeToOriginal = new Map([[MCP_ID, MCP_ID]])
        const out = translateAssistantNamesBack(
            {
                role: 'assistant',
                content: [{ type: 'toolCall', id: 'c', name: MCP_ID, arguments: {} } as unknown],
                api: 'openai-completions',
                model: 'openai/gpt-4o',
                provider: 'openai',
                stopReason: 'toolUse',
                timestamp: 0,
                usage: { input: 0, output: 0, totalTokens: 0, cacheRead: 0, cacheWrite: 0, cost: {} },
            } as unknown as AssistantMessage,
            safeToOriginal
        )
        const call = out.content.find((b) => b.type === 'toolCall') as { name: string }
        expect(call.name).toBe(MCP_ID)
    })

    it('leaves unknown names unchanged (faux provider echoes original verbatim)', () => {
        const out = translateAssistantNamesBack(
            {
                role: 'assistant',
                content: [{ type: 'toolCall', id: 'c', name: 'never_seen', arguments: {} } as unknown],
                api: 'faux',
                model: 'faux',
                provider: 'faux',
                stopReason: 'toolUse',
                timestamp: 0,
                usage: { input: 0, output: 0, totalTokens: 0, cacheRead: 0, cacheWrite: 0, cost: {} },
            } as unknown as AssistantMessage,
            new Map()
        )
        const call = out.content.find((b) => b.type === 'toolCall') as { name: string }
        expect(call.name).toBe('never_seen')
    })
})
